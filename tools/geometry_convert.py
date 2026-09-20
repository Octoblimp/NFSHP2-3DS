#!/usr/bin/env python3
r"""Decode bWare eSolid geometry (chunk 0x80034000) into Wavefront OBJ.

A GEOMETRY.BIN holds one solid list, and a solid list holds one container
chunk per model:

    0x80034000  solid list
      0x00034001   52 bytes   eSolidListHeader -- the source filename
      0x80034002              one per solid
        0x00034003  192 bytes eSolid header (see docs/mdebug_structs.txt)
        0x00034006  n * 8     eTextureTable[]        {NameHash, pTextureInfo}
        0x0003401d  n * 8     eLightMaterialEntry[]  {NameHash, pLightMaterial}
        0x00034004  n * 64    eStripEntry[NumStrips]
        0x00034005            the VU1 packet for every strip, back to back

Chunks are 16-byte aligned by padding the *front* of the payload with 0x11
filler bytes, so 0x00034003 is sometimes 204 bytes and 0x00034004 sometimes
64 * NumStrips + 8.

Each strip's slice of 0x00034005 is `eStripEntry.DataQWordSize * 16` bytes of
raw VIF1 code -- a run of UNPACKs followed by MSCAL and NOP padding.  Replay
them and you get the strip as VU1 micromem saw it, which is the only way to
read the vertices back: the unpack addresses, not the byte order, say what is
what.

    addr   0   V4-8    NumVerts, NumLoops, 3 * NumVerts, 4 * LightMaterialIndex
    addr   1   V4-32   the ADC (kick suppression) bits -- see below
    addr   2   V4-32   XYZ
    addr  32   V4-32   ST
    addr  52   V4-5    RGBA5551, one quad per vertex
    addr  92   V4-8    normals, signed (optional)

XYZ and the normals are stored *transposed*, in groups of four vertices: one
quad of four X, one of four Y, one of four Z, then the next four vertices.  So
vertex v reads lane `v % 4` of

    XYZ      2 + 3 * (v // 4) + component
    normal  92 + 3 * (v // 4) + component

A trailing group of fewer than four vertices keeps that layout and is unpacked
with a narrower VIFcode (S-32/V2-32/V3-32 for XYZ, still V4-8 for normals).
ST is transposed the same way -- one quad of four S, one of four T -- but its
trailing group is *interleaved* instead, S and T pairs packed end to end from
quad `32 + 2 * (NumVerts // 4)`.  Colours are never transposed: the V4-5
unpack expands one RGBA5551 halfword per vertex into the quad at `52 + v`.

The 16 bytes at address 1 are `eStripData::GetADCBits()`'s two words plus
padding, and they are a *per-vertex* bitfield: a set bit means that vertex
does not kick a triangle.  Vertices 0 and 1 are always set, since a strip
needs three vertices before it can draw anything.  Vertex v's bit is

    v <= 14     bit 14 - v                of the low word
    v >= 16     bit 4 * NumLoops + 5 - v  of word 3

and which word is the low one depends only on NumLoops -- word 0 normally,
word 3 for NumLoops 3, word 2 for NumLoops 7.  Vertex 15 has no bit of its
own: the low word's field ends at 14 and the high word's begins at 16.  It
does not need one, because suppressed vertices always come in adjacent pairs
{r, r+1} -- one restart of the strip -- so a lone bit at 14 or 16 implies 15.
That gives eStripEntry.NumPolys exactly for all 22280 strips in the game.
(eSolid.NumPolys disagrees with the sum of its own strips for 19 solids --
that header field is stale in the shipped data, the per-strip counts are the
truth.)

A restart also restarts the winding: the sub-strip beginning at r draws
(r, r+1, r+2) first, so the parity that decides whether a triangle is
(v-2, v-1, v) or (v-2, v, v-1) is measured from r, not from 0.  Checked
against the per-vertex normals this is right for 99.65% of the game's
triangles, the rest being concave corners where a smoothed vertex normal
genuinely disagrees with its face.

Vertex colours are written as extra components on the `v` line, the convention
Blender, MeshLab and Assimp all read.  Each solid becomes one OBJ group, each
strip's light material one OBJ material name.
"""

import argparse
import struct
import sys
from pathlib import Path

SOLID_LIST = 0x80034000
SOLID = 0x80034002
LIST_HEADER = 0x00034001
SOLID_HEADER = 0x00034003
STRIP_ENTRIES = 0x00034004
STRIP_DATA = 0x00034005
TEXTURE_TABLE = 0x00034006
LIGHT_MATERIALS = 0x0003401D

FILLER = 0x11

INFO_ADDR = 0
ADC_ADDR = 1
XYZ_ADDR = 2
ST_ADDR = 32
RGBA_ADDR = 52
NORM_ADDR = 92

# NumLoops -> the quad word holding the ADC bits for vertices 0..14
ADC_LOW_WORD = {0: 0, 1: 0, 2: 0, 3: 3, 4: 0, 5: 0, 6: 0, 7: 2}
ADC_HIGH_WORD = 3
ADC_SPLIT = 16


def chunks(buf, off=0, end=None):
    """Walk a bChunk stream, yielding (type, payload_offset, payload_size)."""
    end = len(buf) if end is None else end
    while off + 8 <= end:
        ctype, size = struct.unpack_from("<II", buf, off)
        if off + 8 + size > end:
            return
        yield ctype, off + 8, size
        off += 8 + size


def unfiller(buf, off, size):
    """Skip the 0x11 bytes bWare pads the front of a chunk with."""
    n = 0
    while n < size and buf[n + off] == FILLER:
        n += 1
    return off + n, size - n


def vifcodes(buf, off, size):
    """Yield (cmd, num, imm, payload_offset, payload_size) for one strip."""
    end = off + size
    while off + 4 <= end:
        word, = struct.unpack_from("<I", buf, off)
        cmd, num, imm = word >> 24, (word >> 16) & 0xFF, word & 0xFFFF
        if cmd == 0x00:                                 # NOP padding
            off += 4
            continue
        if cmd in (0x14, 0x15):                         # MSCAL / MSCALF
            return
        if cmd & 0x60 != 0x60:                          # not an UNPACK
            return
        vn, vl = (cmd >> 2) & 3, cmd & 3
        bits = 16 if vl == 3 else (vn + 1) * (32 >> vl)
        nbytes = ((num * bits + 7) // 8 + 3) & ~3
        yield cmd, num, imm, off + 4, nbytes
        off += 4 + nbytes


def vu_image(buf, off, size):
    """Replay a strip's UNPACKs into (decoded quads, raw 32-bit quads).

    Each address maps to a tuple of one to four components; a narrow VIFcode
    leaves the rest of the quad alone, which is what the VU itself sees.
    """
    mem, raw = {}, {}
    for cmd, num, imm, data, nbytes in vifcodes(buf, off, size):
        addr, vn, vl = imm & 0x3FFF, (cmd >> 2) & 3, cmd & 3
        n, usn, stop = vn + 1, (imm >> 14) & 1, data + nbytes
        width = 2 if vl == 3 else n * (32 >> vl) // 8
        for q in range(num):
            at = data + q * width
            if at + width > stop:
                break
            if vl == 0:                                 # 32-bit
                mem[addr + q] = struct.unpack_from("<%df" % n, buf, at)
                raw[addr + q] = struct.unpack_from("<%dI" % n, buf, at)
            elif vl == 1:                               # 16-bit
                mem[addr + q] = struct.unpack_from("<%d%s" % (n, "H" if usn else "h"), buf, at)
            elif vl == 2:                               # 8-bit
                mem[addr + q] = struct.unpack_from("<%d%s" % (n, "B" if usn else "b"), buf, at)
            else:                                       # 5-bit: one RGBA5551
                w, = struct.unpack_from("<H", buf, at)
                mem[addr + q] = (w & 31, (w >> 5) & 31, (w >> 10) & 31, (w >> 15) & 1)
    return mem, raw


def lane(mem, addr, i, default=0.0):
    """One component out of a VU quad, or `default` if it was never written."""
    v = mem.get(addr)
    return default if v is None or i >= len(v) else v[i]


def suppressed(quad, nverts, nloops):
    """The vertices whose drawing kick the ADC bits cancel."""
    lo, hi = quad[ADC_LOW_WORD[nloops]], quad[ADC_HIGH_WORD]
    base = 4 * nloops + 5
    out = set()
    for v in range(nverts):
        word, bit = (lo, 14 - v) if v < ADC_SPLIT else (hi, base - v)
        if 0 <= bit < 32 and (word >> bit) & 1:
            out.add(v)
    # vertex 15 has no bit; a lone neighbour is the half of a pair that does
    mates = {v + 1 if v < ADC_SPLIT else v - 1
             for v in out if v >= 2 and v - 1 not in out and v + 1 not in out}
    return out | {v for v in mates if 0 <= v < nverts}


def triangles(nverts, dead):
    """Tri-strip indices, with the winding parity restarting at each restart."""
    ref, out = 0, []
    for v in range(nverts):
        if v in dead:
            if v - 1 not in dead:
                ref = v
            continue
        if v >= 2:
            out.append((v - 2, v - 1, v) if (v - ref) % 2 == 0 else (v - 2, v, v - 1))
    return out


def read_strip(buf, off, size):
    """Decode one strip's VU1 packet."""
    mem, raw = vu_image(buf, off, size)
    if INFO_ADDR not in mem or ADC_ADDR not in raw:
        return None
    nverts, nloops, _nbytes, lightmat = (tuple(mem[INFO_ADDR]) + (0, 0, 0, 0))[:4]
    quad = (tuple(raw[ADC_ADDR]) + (0, 0, 0, 0))[:4]
    if not 0 < nverts <= 30 or nloops not in ADC_LOW_WORD:
        return None

    whole = nverts // 4 * 4                     # vertices in full groups of four
    st_tail = ST_ADDR + 2 * (whole // 4)
    has_st, has_norm = ST_ADDR in mem, NORM_ADDR in mem

    pos, st, colour, normal = [], [], [], []
    for v in range(nverts):
        g, i = v // 4, v % 4
        pos.append(tuple(lane(mem, XYZ_ADDR + 3 * g + c, i) for c in range(3)))

        if not has_st:
            st.append((0.0, 0.0))
        elif v < whole:
            st.append((lane(mem, ST_ADDR + 2 * g, i), lane(mem, ST_ADDR + 2 * g + 1, i)))
        else:                                   # the trailing group is interleaved
            k = 2 * (v - whole)
            st.append((lane(mem, st_tail + k // 4, k % 4),
                       lane(mem, st_tail + (k + 1) // 4, (k + 1) % 4)))

        r, gr, b, a = mem.get(RGBA_ADDR + v, (31, 31, 31, 1))
        colour.append((r * 255 // 31, gr * 255 // 31, b * 255 // 31, 255 if a else 0))

        if has_norm:
            normal.append(tuple(lane(mem, NORM_ADDR + 3 * g + c, i, 0) for c in range(3)))

    dead = suppressed(quad, nverts, nloops)
    return {"nverts": nverts, "nloops": nloops, "adc": quad,
            "lightmat_raw": lightmat - 256 if lightmat > 127 else lightmat,
            "lightmat": (lightmat - 256 if lightmat > 127 else lightmat) // 4,
            "pos": pos, "st": st, "colour": colour, "normal": normal or None,
            "dead": sorted(dead), "tris": triangles(nverts, dead)}


def hashes(buf, off, size):
    """The NameHash column of an 8-byte-per-entry table chunk."""
    off, size = unfiller(buf, off, size)
    return [struct.unpack_from("<I", buf, off + i * 8)[0] for i in range(size // 8)]


def read_solid(buf, off, size):
    """Decode one 0x80034002 container."""
    parts = {}
    for ctype, coff, csize in chunks(buf, off, off + size):
        parts[ctype] = (coff, csize)
    if SOLID_HEADER not in parts or STRIP_DATA not in parts:
        return None

    head, _ = unfiller(buf, *parts[SOLID_HEADER])
    namehash, = struct.unpack_from("<I", buf, head + 0x08)
    name = buf[head + 0x10:head + 0x28].split(b"\0")[0].decode("latin-1")
    nstrips, npolys, nverts = struct.unpack_from("<3H", buf, head + 0x34)
    aabb = (struct.unpack_from("<3f", buf, head + 0x40),
            struct.unpack_from("<3f", buf, head + 0x50))

    entries, esize = parts[STRIP_ENTRIES]
    entries += esize - 64 * nstrips                     # filler sits in front
    data_at, data_size = unfiller(buf, *parts[STRIP_DATA])

    lightmats = hashes(buf, *parts[LIGHT_MATERIALS]) if LIGHT_MATERIALS in parts else []
    textures = hashes(buf, *parts[TEXTURE_TABLE]) if TEXTURE_TABLE in parts else []

    strips, skipped, p = [], [], data_at
    for i in range(nstrips):
        e = entries + i * 64
        texnum, = struct.unpack_from("<I", buf, e + 0x00)
        qwords, flags = struct.unpack_from("<2H", buf, e + 0x0C)
        group, ev, ep, elm = struct.unpack_from("<3Bb", buf, e + 0x1C)
        s = read_strip(buf, p, qwords * 16)
        p += qwords * 16
        if s is None:
            skipped.append(i)
            continue
        s.update({"index": i, "qwords": qwords, "entry_texture": texnum,
                  "entry_verts": ev, "entry_polys": ep, "group": group,
                  "entry_lightmat": elm, "flags": flags})
        strips.append(s)
    return {"name": name, "namehash": namehash,
            "nstrips": nstrips, "npolys": npolys, "nverts": nverts,
            "aabb": aabb, "strips": strips, "skipped": skipped,
            "lightmats": lightmats, "textures": textures}


def solids(buf):
    """Every solid in a file, in order."""
    for ctype, off, size in chunks(buf):
        if ctype != SOLID_LIST:
            continue
        for stype, soff, ssize in chunks(buf, off, off + size):
            if stype != SOLID:
                continue
            s = read_solid(buf, soff, ssize)
            if s is not None:
                yield s


def list_name(buf):
    """The source filename the exporter stamped into the solid list."""
    for ctype, off, size in chunks(buf):
        if ctype != SOLID_LIST:
            continue
        for stype, soff, ssize in chunks(buf, off, off + size):
            if stype == LIST_HEADER:
                return buf[soff:soff + 48].split(b"\0")[0].decode("latin-1")
    return ""


def material(strip, solid):
    lm = strip["lightmat"]
    if 0 <= lm < len(solid["lightmats"]):
        return "lm_%08x" % solid["lightmats"][lm]
    return "default"


def write_obj(path, wanted, scale, with_colour):
    """Write the solids as one OBJ, one group each.

    Not every strip carries normals, so `vn` is numbered separately from `v`
    and only the strips that have them get a normal index on their faces.
    """
    vbase = nbase = 1
    used = set()
    with path.open("w", encoding="ascii", newline="\n") as fp:
        fp.write("# extracted by tools/geometry_convert.py\n")
        fp.write("mtllib %s\n" % (path.stem + ".mtl"))
        for solid in wanted:
            fp.write("\no %s\n" % solid["name"])
            placed = []
            for s in solid["strips"]:
                placed.append((s, vbase, nbase if s["normal"] else 0))
                for i in range(s["nverts"]):
                    x, y, z = s["pos"][i]
                    if with_colour:
                        r, g, b, _a = s["colour"][i]
                        fp.write("v %.6f %.6f %.6f %.4f %.4f %.4f\n"
                                 % (x * scale, y * scale, z * scale,
                                    r / 255.0, g / 255.0, b / 255.0))
                    else:
                        fp.write("v %.6f %.6f %.6f\n"
                                 % (x * scale, y * scale, z * scale))
                for u, v in s["st"]:
                    fp.write("vt %.6f %.6f\n" % (u, 1.0 - v))
                for nx, ny, nz in s["normal"] or ():
                    fp.write("vn %.4f %.4f %.4f\n" % (nx / 127.0, ny / 127.0, nz / 127.0))
                vbase += s["nverts"]
                nbase += s["nverts"] if s["normal"] else 0

            for s, voff, noff in placed:
                name = material(s, solid)
                used.add(name)
                fp.write("usemtl %s\n" % name)
                for tri in s["tris"]:
                    if noff:
                        fp.write("f %s\n" % " ".join(
                            "%d/%d/%d" % (voff + i, voff + i, noff + i) for i in tri))
                    else:
                        fp.write("f %s\n" % " ".join(
                            "%d/%d" % (voff + i, voff + i) for i in tri))
    with path.with_suffix(".mtl").open("w", encoding="ascii", newline="\n") as fp:
        fp.write("# light material name hashes, see tools/bhash.py\n")
        for name in sorted(used):
            fp.write("\nnewmtl %s\nKd 1.0 1.0 1.0\n" % name)


def report(path, buf, found):
    """The --list table, with every cross-check the format lets us make."""
    src = list_name(buf)
    print("== %s: %d solids%s ==" % (path, len(found), " from " + src if src else ""))
    print("%-30s %6s %6s %6s %5s %5s" % ("name", "strips", "verts", "polys", "lmat", "tex"))
    bad = stale = 0
    for s in found:
        tris = sum(len(x["tris"]) for x in s["strips"])
        note = ""
        if any(x["entry_polys"] != len(x["tris"]) or x["entry_verts"] != x["nverts"]
               for x in s["strips"]) or len(s["strips"]) != s["nstrips"]:
            note, bad = "   <- decode disagrees with eStripEntry", bad + 1
        elif tris != s["npolys"]:
            note, stale = "   <- %d triangles, eSolid.NumPolys is stale" % tris, stale + 1
        print("%-30s %6d %6d %6d %5d %5d%s"
              % (s["name"], s["nstrips"], s["nverts"], s["npolys"],
                 len(s["lightmats"]), len(s["textures"]), note))
    if bad:
        print("%d solid(s) did not decode cleanly" % bad, file=sys.stderr)
    if stale:
        print("%d solid(s) have a stale eSolid.NumPolys (harmless)" % stale, file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("out", nargs="?", help="output .obj, or a directory with --split")
    ap.add_argument("--list", action="store_true", help="print the solids, convert nothing")
    ap.add_argument("--solid", action="append", metavar="NAME",
                    help="convert only this solid (repeatable, case insensitive)")
    ap.add_argument("--split", action="store_true", help="one OBJ per solid")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--no-colour", action="store_true",
                    help="omit the per-vertex colours from the v lines")
    a = ap.parse_args()
    if not a.list and not a.out:
        ap.error("give an output path, or --list")

    buf = Path(a.file).read_bytes()
    found = list(solids(buf))
    if not found:
        raise SystemExit("no 0x80034000 solid list in %s" % a.file)

    if a.solid:
        want = {n.upper() for n in a.solid}
        found = [s for s in found if s["name"].upper() in want]
        if not found:
            raise SystemExit("no such solid; run with --list to see the names")

    if a.list:
        report(a.file, buf, found)
    elif a.split:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        for s in found:
            safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in s["name"])
            write_obj(out / (safe + ".obj"), [s], a.scale, not a.no_colour)
        print("wrote %d OBJs to %s" % (len(found), out))
    else:
        out = Path(a.out)
        if out.parent != Path(""):
            out.parent.mkdir(parents=True, exist_ok=True)
        write_obj(out, found, a.scale, not a.no_colour)
        print("wrote %d solids, %d triangles to %s"
              % (len(found), sum(len(x["tris"]) for s in found for x in s["strips"]), out))


if __name__ == "__main__":
    main()
