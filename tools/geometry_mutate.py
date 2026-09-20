#!/usr/bin/env python3
"""Mutation-test `tools/geometry_check.py`.

A cross-check that cannot fail proves nothing. Every entry in MUTANTS below
is one single-edit change to `3DS Files/source/geometry.c`, and the check is
expected to notice -- a non-zero `differ` count, or a run that does not
finish. A mutation that changes nothing is either a hole in the test deck or
an equivalent mutant, and the difference matters; see EQUIVALENT.

```
python tools/geometry_mutate.py                 # the whole set, ~5 minutes
python tools/geometry_mutate.py adc-bit-order winding-from-zero
python tools/geometry_mutate.py --list
python tools/geometry_mutate.py --full          # all 30 files, much slower
```

The default file set is four files rather than the checker's thirty:
911TURBO (16 solids, normals, three zero normals), BARCHETTA (15 solids, a
different strip mix), TS50 (whose TS50_C is one of only five solids on the
disc whose texture table starts with a hash ending in 0x11, and so the only
cheap way to reach the chunk-filler rule) and TRACKA12.BUN (no solid list at
all, which is the only file that exercises the failure path). Every mutation
below is caught by that set. `--full` runs the whole disc for when a new
mutation is not caught and the question is whether the deck or the data is
the reason.

This edits a tracked source file in place and puts it back in a `finally`,
so an ordinary failure or a Ctrl-C leaves the tree clean. A hard kill does
not run that, which is what `.mutate-backup` is for: it holds the original
while a run is in flight, and the next run refuses to start until the tree
has been restored from it.
"""
import os
import re
import subprocess
import sys

NL = chr(10)
SRC = "3DS Files/source/geometry.c"
BACKUP = SRC + ".mutate-backup"

CHECK = [sys.executable, "tools/geometry_check.py"]
FAST_FILES = ["--file", "extracted/CARS/911TURBO/GEOMETRY.BIN",
              "--file", "extracted/CARS/BARCHETTA/GEOMETRY.BIN",
              "--file", "extracted/CARS/TS50/GEOMETRY.BIN",
              "--file", "extracted/TRACKS/TRACKA12.BUN"]

# (name, old, new) -- `old` must occur exactly once.
MUTANTS = [
    # ------------------------------------------------------- the chunk tree
    # Both filler mutations keep calling both skip functions, on a throwaway
    # copy of the cursor where that is the point of the mutation. Dropping the
    # call instead leaves a static function with no callers, and then it is
    # the compiler that catches the mutation and not the cross-check, which
    # tells us nothing about the deck.
    ("index-skips-unfiller",
     "        if (c.type == TYPE_TEXTURES || c.type == TYPE_LIGHT_MATS) {" + NL
     + "            unfiller_table(&p, &n);" + NL
     + "        } else {" + NL
     + "            unfiller(&p, &n);" + NL
     + "        }",
     "        {" + NL
     + "            const uint8_t* t = p;" + NL
     + "            size_t         u = n;" + NL
     + "            unfiller_table(&t, &u);" + NL
     + "            unfiller(&t, &u);" + NL
     + "        }"),
    # The byte-at-a-time scan, which is what unfiller_table exists to replace.
    # Only TS50_C and the four XS_CURVE35 track pieces have a texture table
    # whose first hash ends in 0x11, so this needs TS50 in the file set to be
    # caught at all -- which is why TS50 is in FAST_FILES.
    ("table-filler-byte-at-a-time",
     "    int            i;" + NL + NL
     + "    for (;;) {" + NL
     + "        if (n + TABLE_ENTRY_SIZE > *size) {" + NL
     + "            break;" + NL
     + "        }" + NL
     + "        for (i = 0; i < TABLE_ENTRY_SIZE; i++) {" + NL
     + "            if (q[n + i] != CHUNK_FILLER) {" + NL
     + "                break;" + NL
     + "            }" + NL
     + "        }" + NL
     + "        if (i != TABLE_ENTRY_SIZE) {" + NL
     + "            break;" + NL
     + "        }" + NL
     + "        n += TABLE_ENTRY_SIZE;" + NL
     + "    }",
     "    while (n < *size && q[n] == CHUNK_FILLER) {" + NL
     + "        n++;" + NL
     + "    }"),
    ("texcount-back-to-header",
     "    s->numTextures = (int)(textureBytes / TABLE_ENTRY_SIZE);",
     "    (void)textureBytes;" + NL + "    s->numTextures = 0;"),
    ("texcount-wrong-stride",
     "(int)(textureBytes / TABLE_ENTRY_SIZE)",
     "(int)(textureBytes / 16)"),
    ("lightmat-count-from-dead-field",
     "    s->numLightMaterials = rd16(p + SOLID_NUM_LIGHTMAT);",
     "    s->numLightMaterials = rd16(p + 0xac);"),
    ("aabb-max-is-min",
     "    rdf32v(p + SOLID_AABB_MAX, s->aabbMax, 3);",
     "    rdf32v(p + SOLID_AABB_MIN + 12, s->aabbMax, 3);"),
    ("strip-texture-number-offset",
     "    out->textureNumber  = (int)rd32(p + STRIP_TEX_NUMBER);",
     "    out->textureNumber  = (int)rd32(p + STRIP_TEX_NUMBER + 4);"),
    ("strip-entry-stride",
     "    p = solid->stripEntries + (size_t)index * STRIP_ENTRY_SIZE;",
     "    p = solid->stripEntries + (size_t)index * 60;"),

    # ------------------------------------------------------- the VIF replay
    ("unpack-mask-admits-mscal",
     "#define VIF_IS_UNPACK(cmd)  (((cmd) & 0x60) == 0x60)",
     "#define VIF_IS_UNPACK(cmd)  ((((cmd) & 0x60) == 0x60) || (cmd) == 0x14)"),
    ("unpack-vn-vl-swapped",
     "            int    vn   = (int)((cmd >> 2) & 3);" + NL
     + "            int    vl   = (int)(cmd & 3);",
     "            int    vn   = (int)(cmd & 3);" + NL
     + "            int    vl   = (int)((cmd >> 2) & 3);"),
    ("unpack-addr-mask",
     "            int    addr = (int)(imm & 0x3fff);",
     "            int    addr = (int)(imm & 0x3ffe);"),
    ("unpack-v4-5-width",
     "        return vn == 3 ? 2 : 0;",
     "        return vn == 3 ? 4 : 0;"),
    ("unpack-item-width",
     "    return (vn + 1) * (vl == 0 ? 4 : vl == 1 ? 2 : 1);",
     "    return (vn + 1) * (vl == 0 ? 4 : vl == 1 ? 1 : 2);"),
    ("unpack-lane-count",
     "        for (i = 0; i <= vn; i++) {",
     "        for (i = 0; i < vn; i++) {"),
    ("unpack-writes-one-quad",
     "                unpack_write(vu, addr + i, vn, vl, usn,",
     "                unpack_write(vu, addr, vn, vl, usn,"),
    ("unpack-no-word-align",
     "            off += (data + 3u) & ~(size_t)3;",
     "            off += data;"),
    ("unpack-v4-5-lane",
     "        lane[0] = rd16(p);",
     "        lane[3] = rd16(p);"),
    ("unpack-forgets-written",
     "    vu->written[addr] = 1;",
     "    vu->written[addr] = (uint8_t)(addr != VU_NORMAL);"),

    # ------------------------------------------------- reading the fields back
    ("transposed-stride",
     "    return base + 3 * (v / 4) + component;",
     "    return base + 4 * (v / 4) + component;"),
    ("transposed-group-size",
     "    return base + 3 * (v / 4) + component;",
     "    return base + 3 * (v / 3) + component;"),
    ("vertex-lane",
     "        int        lane = v % 4;",
     "        int        lane = v % 3;"),
    ("xyz-component-order",
     "            dst->pos[c] = lane_f32(&vu, transposed_quad(VU_XYZ, v, c), lane);",
     "            dst->pos[c] = lane_f32(&vu, transposed_quad(VU_XYZ, v, 2 - c), lane);"),
    # ST: two vertices to a quad, the odd one's pair mirrored. Each of these
    # is a reading that was plausible enough to ship once; see
    # docs/formats/solid-geometry.md.
    ("st-one-vertex-per-quad",
     "    *quad = VU_ST + (v >> 1);",
     "    *quad = VU_ST + v;"),
    ("st-transposed-like-xyz",
     "    *quad = VU_ST + (v >> 1);" + NL
     + "    *lane = (v & 1) ? 3 - component : component;",
     "    *quad = VU_ST + 2 * (v / 4) + component;" + NL
     + "    *lane = v % 4;"),
    ("st-not-mirrored",
     "    *lane = (v & 1) ? 3 - component : component;",
     "    *lane = (v & 1) ? 2 + component : component;"),
    ("st-parity-inverted",
     "    *lane = (v & 1) ? 3 - component : component;",
     "    *lane = (v & 1) ? component : 3 - component;"),
    ("rgba-transposed-too",
     "        dst->colour = (uint16_t)(vu.q[VU_RGBA + v][0] & 0xffffu);",
     "        dst->colour = (uint16_t)(vu.q[VU_RGBA + v / 4][v % 4] & 0xffffu);"),
    ("rgba-channel-shift",
     "        dst->colour = (uint16_t)(vu.q[VU_RGBA + v][0] & 0xffffu);",
     "        dst->colour = (uint16_t)((vu.q[VU_RGBA + v][0] >> 1) & 0xffffu);"),
    ("normal-quad-base",
     "                quad = transposed_quad(VU_NORMAL, v, c);",
     "                quad = transposed_quad(VU_NORMAL + 1, v, c);"),
    ("normal-wrong-byte",
     "                    dst->normal[c] = (int8_t)(vu.q[quad][lane] & 0xffu);",
     "                    dst->normal[c] = (int8_t)((vu.q[quad][lane] >> 8) & 0xffu);"),
    ("hasnormals-always",
     "    out->hasNormals = vu.written[VU_NORMAL];",
     "    out->hasNormals = 1;"),
    ("numverts-from-wrong-lane",
     "    numVerts = (int)(vu.q[VU_HEADER][0] & 0xffu);",
     "    numVerts = (int)(vu.q[VU_HEADER][2] & 0xffu);"),
    ("numloops-from-wrong-lane",
     "    numLoops = (int)(vu.q[VU_HEADER][1] & 0xffu);",
     "    numLoops = (int)(vu.q[VU_HEADER][2] & 0xffu);"),
    ("lightmat-unsigned",
     "    out->lightMaterial = (int)(int8_t)(vu.q[VU_HEADER][3] & 0xffu) / 4;",
     "    out->lightMaterial = (int)(uint8_t)(vu.q[VU_HEADER][3] & 0xffu) / 4;"),
    ("lightmat-divide",
     "    out->lightMaterial = (int)(int8_t)(vu.q[VU_HEADER][3] & 0xffu) / 4;",
     "    out->lightMaterial = (int)(int8_t)(vu.q[VU_HEADER][3] & 0xffu) / 2;"),

    # ------------------------------------------------------------- the ADC bits
    ("adc-low-word-3",
     "    case 3:  return 3;",
     "    case 3:  return 0;"),
    ("adc-low-word-7",
     "    case 7:  return 2;",
     "    case 7:  return 0;"),
    ("adc-bit-order",
     "        bit = 14 - v;",
     "        bit = v;"),
    ("adc-split-at-15",
     "    if (v <= 14) {",
     "    if (v <= 15) {"),
    ("adc-high-base",
     "        bit = 4 * numLoops + 5 - v;",
     "        bit = 4 * numLoops + 4 - v;"),
    ("adc-high-word",
     "        return (int)((adc[3] >> bit) & 1u);",
     "        return (int)((adc[2] >> bit) & 1u);"),
    ("adc-range-guard-off-by-one",
     "    if (v < 0 || v >= numVerts) {",
     "    if (v < 0 || v > numVerts) {"),
    ("adc-v15-never",
     "    return (adc_bit(adc, numLoops, numVerts, 14)" + NL
     + "            && !adc_bit(adc, numLoops, numVerts, 13))" + NL
     + "        || (adc_bit(adc, numLoops, numVerts, 16)" + NL
     + "            && !adc_bit(adc, numLoops, numVerts, 17));",
     "    return 0;"),
    ("adc-v15-first-half-only",
     "    return (adc_bit(adc, numLoops, numVerts, 14)" + NL
     + "            && !adc_bit(adc, numLoops, numVerts, 13))" + NL
     + "        || (adc_bit(adc, numLoops, numVerts, 16)" + NL
     + "            && !adc_bit(adc, numLoops, numVerts, 17));",
     "    return (adc_bit(adc, numLoops, numVerts, 14)" + NL
     + "            && !adc_bit(adc, numLoops, numVerts, 13));"),
    ("adc-v15-drops-the-guard",
     "    return (adc_bit(adc, numLoops, numVerts, 14)" + NL
     + "            && !adc_bit(adc, numLoops, numVerts, 13))" + NL
     + "        || (adc_bit(adc, numLoops, numVerts, 16)" + NL
     + "            && !adc_bit(adc, numLoops, numVerts, 17));",
     "    return adc_bit(adc, numLoops, numVerts, 14)" + NL
     + "        || adc_bit(adc, numLoops, numVerts, 16);"),

    # ---------------------------------------------------------- the winding
    ("winding-from-zero",
     "        if (((v - start) & 1) == 0) {",
     "        (void)start;" + NL + "        if ((v & 1) == 0) {"),
    ("winding-flipped",
     "        if (((v - start) & 1) == 0) {",
     "        if (((v - start) & 1) != 0) {"),
    ("winding-restart-unconditional",
     "            if (!adc_bit(out->adc, numLoops, numVerts, v - 1)) {" + NL
     + "                start = v;              // the first of the pair" + NL
     + "            }",
     "            start = v;"),
    ("winding-never-restarts",
     "            if (!adc_bit(out->adc, numLoops, numVerts, v - 1)) {" + NL
     + "                start = v;              // the first of the pair" + NL
     + "            }",
     "            (void)0;"),
    ("winding-restart-off-by-one",
     "                start = v;              // the first of the pair",
     "                start = v - 1;"),
    ("tri-first-index",
     "        out->tri[out->numTris][0] = (uint8_t)(v - 2);",
     "        out->tri[out->numTris][0] = (uint8_t)(v - 1);"),
    # ---------------------------------------------- walking the packet in order
    ("cursor-does-not-advance",
     "    cursor->offset += (size_t)entry.dataQWordSize * 16u;",
     "    cursor->offset += 0;"),
    ("qword-size",
     "    size = (size_t)entry->dataQWordSize * 16u;",
     "    size = (size_t)entry->dataQWordSize * 8u;"),
]

# Changes that provably cannot alter the transcript. Listed so that a future
# reader does not "fix" the deck by adding them, and because each one is a
# fact about the data worth having written down.
EQUIVALENT = [
    ("numverts-from-entry",
     "eStripEntry's NumVerts, NumPolys and LightMaterialIndex agree with the "
     "VU packet's own header quad on all 18,848 strips of the disc, so "
     "reading either one gives the same answer. That redundancy is what "
     "lets a renderer size its buffers from the 64-byte entry table without "
     "replaying a single packet."),
    ("unpack-usn-bit",
     "The UNPACK USN bit selects zero- or sign-extension into the VU quad, "
     "but every field this decoder reads back is re-extended at the point "
     "of use -- normals through (int8_t), the header bytes through & 0xff, "
     "XYZ and ST as raw 32-bit patterns. So usn cannot reach the output and "
     "flipping it changes nothing. It is kept because unpack_write models "
     "the VU, not this decoder's needs."),
    ("unpack-mask-any-bit",
     "Relaxing `(cmd & 0x60) == 0x60` to `(cmd & 0x60) != 0` changes nothing, "
     "because no VIFcode with only one of those two bits set occurs. A census "
     "of every packet on the disc finds exactly seven distinct CMD bytes in "
     "18,848 strips: MSCAL 0x14, and the six UNPACKs 0x60 (S-32), 0x64 "
     "(V2-32), 0x68 (V3-32), 0x6c (V4-32), 0x6e (V4-8) and 0x6f (V4-5). "
     "Every one of them ANDs to 0x00 or 0x60 and none to 0x20 or 0x40, so "
     "the two tests agree everywhere. The replacement mutation above, which "
     "admits MSCAL, is the one that discriminates."),
    ("strip-texture-number-width",
     "Reading eStripEntry.TextureNumber as 16 bits rather than 32 is "
     "equivalent: the field never exceeds 27 anywhere on the disc, so its "
     "top half is always zero. It is read as the u32 the struct declares "
     "rather than the u16 the data would allow, because the day a solid has "
     "more than 65,535 textures is not the day to discover this."),
    ("tri-loop-start",
     "Starting the triangle loop at vertex 1 instead of 2 draws nothing "
     "extra, because ADC bits 0 and 1 are set on all 18,848 strips of the "
     "disc without exception -- a strip needs three vertices before it can "
     "kick anything. Vertex 1's iteration is suppressed, and the restart "
     "guard it would trip reads bit 0, which is also set, so `start` does "
     "not move either. The loop bound is documentation, not a rule the data "
     "leans on."),
    ("adc-past-end-is-set",
     "Making the out-of-range guard return 1 instead of 0 is equivalent, "
     "but only just, and the reason is worth writing down. The guard is "
     "reached from exactly two places: `adc_bit(.., v - 1)` with v >= 2, "
     "which is always in range, and the vertex-15 rule, which asks about "
     "vertices 13, 14, 16 and 17. At 16 vertices both 16 and 17 fall off "
     "the end, and since the rule is `bit(16) && !bit(17)` the two cancel "
     "whichever constant the guard returns. At 17 vertices only 17 falls "
     "off, so the mutation would change the answer for any such strip whose "
     "bit 16 is set -- and of the 75 strips on the disc with exactly 17 "
     "vertices, not one has it. The guard is therefore right and untested "
     "by this data; `adc-range-guard-off-by-one` above mutates the same "
     "line in a way the data does reach."),
    ("v4-5-lanes-1-to-3",
     "The V4-5 unpack expands one RGBA5551 halfword into four fields, but "
     "the port keeps it packed in lane 0 and geo_unpack_colour splits it "
     "later. Nothing reads lanes 1..3 of a colour quad, so writing them or "
     "not is invisible."),
]


def read():
    # geometry.c is LF and must stay that way.
    with open(SRC, "r", newline="") as fh:
        return fh.read()


def write(text):
    with open(SRC, "w", newline="") as fh:
        fh.write(text)


def backup_take(original):
    """Park the pristine source where a killed run can be recovered from."""
    if os.path.exists(BACKUP):
        sys.exit("%s already exists, which means a previous run was killed "
                 "while the source was mutated. Compare it against %s and "
                 "restore by hand, then delete it." % (BACKUP, SRC))
    with open(BACKUP, "w", newline="") as fh:
        fh.write(original)


def backup_drop():
    if os.path.exists(BACKUP):
        os.remove(BACKUP)


def run_check(cmd):
    """-> (label, caught, warned).

    `caught` means the cross-check noticed: a non-zero differ count, or a run
    that did not finish. `warned` means the mutant did not compile cleanly --
    a defect in the mutation, not a result, because a warning is the compiler
    catching it rather than the checker.

    hostbuild prints `compiler warnings:` as the *first* line of stdout and
    keeps going, so reading line 1 reports the warning and hides why the run
    actually stopped.
    """
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return "did not finish in 1800s", True, False

    out = (r.stdout or "") + (r.stderr or "")
    warned = "compiler warnings:" in out

    for line in out.splitlines():
        m = re.search(r"([0-9]+) differ", line)
        if m:
            n = int(m.group(1))
            return "%d lines differ" % n, n > 0, warned

    lines = [ln.strip() for ln in out.strip().splitlines() if ln.strip()]
    reason = "no differ line"
    for line in lines:
        if line.startswith(("harness failed", "compile failed",
                            "harness did not finish")):
            reason = line.rstrip(":")
            break
    else:
        for line in reversed(lines):
            if not line.startswith("compiler warnings:"):
                reason = line
                break
    return reason[:60], r.returncode != 0, warned


def main():
    flags = [a for a in sys.argv[1:] if a.startswith("-")]
    only = [a for a in sys.argv[1:] if not a.startswith("-")]

    if "--list" in flags:
        for name, _, _ in MUTANTS:
            print(name)
        for name, why in EQUIVALENT:
            print("%s   (equivalent, not counted)" % name)
            print("    %s" % why)
        return 0

    cmd = CHECK if "--full" in flags else CHECK + FAST_FILES

    original = read()
    unknown = [a for a in only if a not in [m[0] for m in MUTANTS]]
    if unknown:
        sys.exit("unknown mutation: %s" % ", ".join(unknown))

    # Every pattern is validated, not just the selected ones: a pattern that
    # has rotted away from the source is the failure this catches, and it is
    # silent if only the ones about to run are checked.
    for name, old, new in MUTANTS:
        if old not in original:
            sys.exit("pattern for %s does not match the source" % name)
        if original.count(old) != 1:
            sys.exit("pattern for %s matches %d times"
                     % (name, original.count(old)))

    label, caught, warned = run_check(cmd)
    print("%-32s %s" % ("(baseline)", label))
    if caught or warned:
        sys.exit("baseline does not pass clean; fix that first")

    results = []
    backup_take(original)
    try:
        for name, old, new in MUTANTS:
            if only and name not in only:
                continue
            write(original.replace(old, new))
            label, caught, warned = run_check(cmd)
            results.append((name, label, caught, warned))
            print("%-32s %-34s %s%s"
                  % (name, label, "caught" if caught else "MISSED",
                     "  (does not compile clean)" if warned else ""))
    finally:
        write(original)
        backup_drop()

    n = len(results)
    got = len([r for r in results if r[2]])
    print("")
    print("%d/%d mutations caught" % (got, n))
    missed = [r[0] for r in results if not r[2]]
    if missed:
        print("missed: %s" % ", ".join(missed))
    warns = [r[0] for r in results if r[3]]
    if warns:
        print("did not compile clean: %s" % ", ".join(warns))
    return 0 if got == n and not warns else 1


if __name__ == "__main__":
    sys.exit(main())
