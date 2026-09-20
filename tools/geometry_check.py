#!/usr/bin/env python3
"""Cross-check `3DS Files/source/geometry.c` against tools/geometry_convert.py.

Every other checker in this directory drives scripted scenarios, because the
only oracle available was a second implementation written from the same
disassembly. This one is different, and it is worth being precise about why.

`tools/geometry_convert.py` came first and was validated against the shipped
data rather than against any port: every vertex of all 1,465 solids falls
inside its own solid's AABB, the ADC rule reproduces `eStripEntry.NumPolys`
for all 22,280 strips, and the winding it derives agrees with the per-vertex
normals on 99.65% of triangles. So the Python is the reference here, the C is
the thing under test, and the input is the disc itself -- 28 car geometry
files and the track bundles, not a script.

A per-vertex dump of that would be tens of millions of lines, so the
transcript carries a digest per strip and per solid (FNV-1a, four lines in
either language and no table, so the two cannot drift) plus the invariant
counts recomputed independently on both sides. `--detail NAME` switches one
named solid to a full per-vertex dump on both sides, which is what to reach
for when a digest differs.

    python tools/geometry_check.py
    python tools/geometry_check.py --file extracted/CARS/911TURBO/GEOMETRY.BIN
    python tools/geometry_check.py --file ... --detail 911TURBO_SIDE_MIRROR_LE
"""
import argparse
import difflib
import glob
import os
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geometry_convert as gc
import hostbuild

NL = chr(10)
CR = chr(13)
BS = chr(92)

SOURCES = ["3DS Files/source/geometry.c", "tools/src/geometry_test.c"]

# What the harness is compiled with. It indexes a whole track bundle, so the
# solid array is the one thing here that is not free.
MAX_SOLIDS = 1400

# The disc, in the order the transcript walks it. Cars first because they are
# small enough to read a diff in; the bundles last because TRACKB12 alone is
# 1,135 solids and dominates the line count.
DEFAULT_FILES = (sorted(glob.glob("extracted/CARS/*/GEOMETRY.BIN"))
                 + ["extracted/TRACKS/TRACKA12.BUN",
                    "extracted/TRACKS/TRACKB12.BUN"])

FNV_OFFSET = 2166136261
FNV_PRIME = 16777619
MASK = 0xffffffff

# Matches the bound in tools/src/geometry_test.c; see the comment there and
# the "Normals" paragraph of docs/formats/solid-geometry.md.
NORM_MIN2 = 125 * 125
NORM_MAX2 = 127 * 127


# ------------------------------------------------------------------ the digest

def fnv_byte(h, b):
    return ((h ^ (b & 0xff)) * FNV_PRIME) & MASK


def fnv_u32(h, v):
    v &= MASK
    for shift in (0, 8, 16, 24):
        h = fnv_byte(h, (v >> shift) & 0xff)
    return h


def fnv_f32(h, f):
    bits, = struct.unpack("<I", struct.pack("<f", f))
    return fnv_u32(h, bits)


# ----------------------------------------------------------------- the model

def short_name(path):
    """The last two components, byte for byte the way the harness prints them.

    The harness returns a pointer into the argv string, so whichever
    separator the caller used survives -- and on this machine glob() hands
    back backslashes. Slicing rather than re-joining keeps the two in step.
    """
    cut = [i for i, ch in enumerate(path) if ch in ("/", BS)]
    return path[cut[-2] + 1:] if len(cut) >= 2 else (
        path[cut[-1] + 1:] if cut else path)


def lightmat(raw):
    """eStripData's light-material byte, divided the way the C divides it.

    The port writes `(int8_t)byte / 4`, and C's `/` truncates toward zero
    while Python's `//` floors, so -6 is -1 there and -2 here. Spell out the
    C's rule rather than letting the two disagree on negatives only.
    """
    q = abs(int(raw)) // 4
    return -q if raw < 0 else q


def strip_digest(s, has_norm):
    h = FNV_OFFSET
    h = fnv_u32(h, s["nverts"])
    h = fnv_u32(h, len(s["tris"]))
    h = fnv_u32(h, 1 if has_norm else 0)
    h = fnv_u32(h, lightmat(s["lightmat_raw"]) & 0xff)

    for v in range(s["nverts"]):
        for c in s["pos"][v]:
            h = fnv_f32(h, c)
        for c in s["st"][v]:
            h = fnv_f32(h, c)
        for c in s["colour"][v]:
            h = fnv_byte(h, c)
        if has_norm:
            for c in s["normal"][v]:
                h = fnv_byte(h, c)
    for t in s["tris"]:
        for i in t:
            h = fnv_byte(h, i)
    return h


def dump_strip_detail(out, s, has_norm):
    for v in range(s["nverts"]):
        x, y, z = s["pos"][v]
        u, w = s["st"][v]
        r, g, b, a = s["colour"][v]
        line = ("      v%-2d %.6f %.6f %.6f  st %.6f %.6f  rgba %d %d %d %d"
                % (v, x, y, z, u, w, r, g, b, a))
        if has_norm:
            line += "  n %d %d %d" % tuple(s["normal"][v])
        out.append(line)
    for t, tri in enumerate(s["tris"]):
        out.append("      t%-2d %d %d %d" % (t, tri[0], tri[1], tri[2]))


def dump_solid(out, buf, off, size, index, detail, totals):
    s = gc.read_solid(buf, off, size)
    if s is None:
        # The harness stops on a solid it cannot index rather than skipping
        # one, so a difference here is real and should be loud.
        out.append("solid %d UNREADABLE" % index)
        return

    strips = tris = polys = outside = bad = zero = skipped = 0
    digest = FNV_OFFSET

    out.append("solid %d '%s' hash=%08x strips=%d verts=%d polys=%d "
               "tex=%d lmat=%d"
               % (index, s["name"], s["namehash"], s["nstrips"], s["nverts"],
                  s["npolys"], len(s["textures"]), len(s["lightmats"])))
    lo, hi = s["aabb"]
    out.append("  aabb %.6f %.6f %.6f  %.6f %.6f %.6f"
               % (lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]))

    by_index = {st["index"]: st for st in s["strips"]}
    for at in range(s["nstrips"]):
        st = by_index.get(at)
        if st is None:
            out.append("  strip %d unreadable: malformed chunk" % at)
            skipped += 1
            continue

        has_norm = bool(st["normal"])
        d = strip_digest(st, has_norm)
        digest = fnv_u32(digest, d)

        strips += 1
        tris += len(st["tris"])
        polys += st["entry_polys"]
        for v in range(st["nverts"]):
            p = st["pos"][v]
            if any(p[i] < lo[i] or p[i] > hi[i] for i in range(3)):
                outside += 1
            if has_norm:
                n = st["normal"][v]
                len2 = n[0] * n[0] + n[1] * n[1] + n[2] * n[2]
                if not len2:
                    zero += 1
                elif not NORM_MIN2 <= len2 <= NORM_MAX2:
                    bad += 1

        out.append("  strip %d e.verts=%d e.polys=%d e.lmat=%d e.tex=%d "
                   "qwords=%d group=%d flags=%04x"
                   % (at, st["entry_verts"], st["entry_polys"],
                      st["entry_lightmat"], st["entry_texture"],
                      st["qwords"], st["group"], st["flags"]))
        adc = st["adc"]
        out.append("    verts=%d tris=%d lmat=%d normals=%d "
                   "adc %08x %08x %08x %08x digest %08x"
                   % (st["nverts"], len(st["tris"]),
                      lightmat(st["lightmat_raw"]), 1 if has_norm else 0,
                      adc[0], adc[1], adc[2], adc[3], d))
        if s["name"] in detail:
            dump_strip_detail(out, st, has_norm)

    out.append("  checks strips=%d tris=%d entrypolys=%d outside=%d "
               "badnormals=%d zeronormals=%d skipped=%d digest %08x"
               % (strips, tris, polys, outside, bad, zero, skipped, digest))

    totals["strips"] += strips
    totals["tris"] += tris
    totals["polys"] += polys
    totals["outside"] += outside
    totals["bad"] += bad
    totals["zero"] += zero
    totals["skipped"] += skipped


def model(path, detail):
    buf = open(path, "rb").read()
    out = []
    totals = dict.fromkeys(
        ("strips", "tris", "polys", "outside", "bad", "zero", "skipped"), 0)

    # The same walk geo_open does: every 0x00034002 in the tree, in file
    # order, counted whether or not it fits in the caller's array.
    found = []
    for ctype, off, size in gc.chunks(buf):
        if ctype != gc.SOLID_LIST:
            continue
        for stype, soff, ssize in gc.chunks(buf, off, off + size):
            if stype == gc.SOLID:
                found.append((soff, ssize))

    out.append("file %s" % short_name(path))
    if not found:
        out.append("open failed: no 0x80034000 solid list in the buffer")
        return out
    out.append("source %s" % gc.list_name(buf))
    shown = min(len(found), MAX_SOLIDS)
    out.append("solids %d of %d" % (shown, len(found)))

    for i, (soff, ssize) in enumerate(found[:MAX_SOLIDS]):
        dump_solid(out, buf, soff, ssize, i, detail, totals)

    out.append("totals solids=%d strips=%d tris=%d entrypolys=%d outside=%d"
               " badnormals=%d zeronormals=%d skipped=%d"
               % (shown, totals["strips"], totals["tris"], totals["polys"],
                  totals["outside"], totals["bad"], totals["zero"],
                  totals["skipped"]))
    return out


# ------------------------------------------------------------------- driving

# The whole disc is 42,047 lines. A mutant that loses its place can print
# without bound -- one that made vif_replay reject every packet got 72
# million lines out in sixty seconds -- so the transcript is capped well
# above anything real and treated as a failure past that.
MAX_LINES = 2000000


def run_harness(exe, path, detail, tmp):
    """Run the harness on one file and return its transcript as lines.

    stdout goes to a file rather than a pipe. That matters more than it
    looks: with capture_output the parent has to drain a pipe the child is
    filling, and a runaway child leaves the two deadlocked with the timeout
    unable to help, because killing a cygwin-built exe from Windows does not
    reliably close its handles. A file has no such handshake -- the child
    dies, the bytes that made it are on disk, and the timeout works.
    """
    out = os.path.join(tmp, "harness.txt")
    with open(out, "wb") as fh:
        try:
            r = subprocess.run([str(exe), path] + detail, stdout=fh,
                               stderr=subprocess.PIPE, timeout=300)
        except subprocess.TimeoutExpired:
            sys.exit("harness did not finish within 300s on %s "
                     "(%d bytes of output so far)"
                     % (path, os.path.getsize(out)))

    if r.returncode != 0:
        why = "exit %d" % r.returncode
        if r.returncode > 255 and r.returncode % 256 == 0:
            why = "killed by signal %d" % (r.returncode // 256)
        err = (r.stderr or b"").decode("utf-8", "replace")
        sys.exit("harness failed on %s (%s):%s%s"
                 % (path, why, NL, err or "(nothing on stderr)"))

    with open(out, "r", encoding="utf-8", errors="replace", newline="") as fh:
        text = fh.read()
    lines = text.replace(CR + NL, NL).rstrip(NL).split(NL)
    if len(lines) > MAX_LINES:
        sys.exit("harness printed %d lines on %s, which is not a transcript"
                 % (len(lines), path))
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append",
                    help="check only this file (repeatable)")
    ap.add_argument("--detail", action="append", default=[],
                    help="dump every vertex of this solid (repeatable)")
    ap.add_argument("--dump", help="write both transcripts next to this path")
    args = ap.parse_args()

    files = args.file or [p for p in DEFAULT_FILES if os.path.exists(p)]
    missing = [p for p in files if not os.path.exists(p)]
    if missing:
        sys.exit("no such file: %s" % missing[0])
    if not files:
        sys.exit("no geometry to check; run the extractor first")

    port, ours = [], []
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, name="geometry_test")
        for path in files:
            port += run_harness(exe, path, args.detail, tmp)
            ours += model(path, set(args.detail))

    if args.dump:
        for name, lines in (("port", port), ("model", ours)):
            with open("%s.%s.txt" % (args.dump, name), "w", newline=NL) as fh:
                fh.write(NL.join(lines) + NL)

    diff = list(difflib.unified_diff(port, ours, "port", "model",
                                     lineterm="", n=1))
    n = len([ln for ln in diff
             if ln[:1] in "+-" and not ln.startswith(("+++", "---"))])
    print("%d files, %d lines, %d differ" % (len(files), len(port), n))
    if diff:
        print(NL.join(diff[:120]))
        if len(diff) > 120:
            print("... %d more diff lines" % (len(diff) - 120))
    return 1 if diff else 0


if __name__ == "__main__":
    sys.exit(main())
