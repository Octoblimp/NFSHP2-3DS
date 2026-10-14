#!/usr/bin/env python3
"""Checks the editable bake and its refresh (`3DS Files/source/geobake.c`)
on the disc's cars.

TASKS 51c: CarDamage's walk (estripdata.c) dents a car's vertices, steps
their colours and shows or hides its scuff strips in the solid's packet,
and the port draws a solid from a mesh baked out of the packet. A car's
solid that BodyDamage walks is baked editable, and georender_refresh reads
the packet back into the mesh. A refresh that missed a vertex, wrote it to
the wrong place, or left a scuff strip drawn would show only as a car
drawn wrong, so this builds geobake.c on the host with geometry.c,
geocull.c and estripdata.c (tools/src/geobake_test.c) and runs it over
every solid of every car's GEOMETRY.BIN under extracted-retail/CARS:

  - with every scuff strip shown, the editable bake is the plain bake,
    byte for byte, and a refresh before any change changes nothing;
  - three times over: each strip vertex moved and recoloured in the
    packet by a hash of what it holds (so the vertices the bake merged
    change alike, as CarDamage's keys change them), each scuff strip
    shown or hidden at random, and the mesh refreshed; it must draw what
    an editable bake of the changed solid draws, at each index the same
    vertex byte for byte, in the same batches with the same boxes; and
    the triangles it draws (none of whose corners share an index) must
    be the plain bake's, in order, vertex for vertex, in batches of the
    same texture, flags and material, which has exactly the hidden scuff
    strips' triangles fewer.

    python tools/geobake_check.py
    python tools/geobake_check.py --mutate [--only a,b]
"""
import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

HARNESS = "tools/src/geobake_test.c"
GB = "3DS Files/source/geobake.c"
SOURCES = [HARNESS, GB, "3DS Files/source/geometry.c",
           "3DS Files/source/geocull.c", "3DS Files/source/estripdata.c"]
CARS = ROOT / "extracted-retail" / "CARS"


def files():
    got = sorted(str(p) for p in CARS.glob("*/GEOMETRY.BIN"))
    if not got:
        sys.exit("no extracted-retail/CARS/*/GEOMETRY.BIN")
    return got


def build_harness(tmp):
    return hostbuild.build(tmp, SOURCES, name="geobake_test")


diff = pcc.diff


# ============================================================= mutations

def M(name, before, after):
    return (name, GB, before, after)


MUTATIONS = [
    # -- the bake
    M("gb-keep-hidden", "if (hidden && !(editable && (entry.flags & ESTRIP_SCUFFS)))",
      "if (hidden)"),
    M("gb-plain-hidden", "if (hidden && !(editable && (entry.flags & ESTRIP_SCUFFS)))",
      "if (hidden && 0)"),
    M("gb-batch-hidden", "order[n].flags   = (uint16_t)(entry.flags & ~ESTRIP_HIDDEN);",
      "order[n].flags   = entry.flags;"),
    M("gb-vert-first", "vertFirst[i + 1] += entry.numVerts;",
      "vertFirst[i + 1] += entry.numPolys;"),
    M("gb-remap-first", "if (local[c] >= 0) {\n                    remap",
      "if (local[c] > 0) {\n                    remap"),
    M("gb-remap-have", "for (c = 0; c < strip->numVerts && c < have; c++) {",
      "for (c = 0; c < strip->numVerts && c < have - 1; c++) {"),
    M("gb-toggle-none", "if ((order[i].flags & ESTRIP_SCUFFS) && at > first) {",
      "if (0) {"),
    M("gb-toggle-hidden", "toggle[numToggles].kept  = order[i].hidden ? 1 : 0;",
      "toggle[numToggles].kept  = 0;"),
    M("gb-toggle-count", "toggle[numToggles].count = at - first;",
      "toggle[numToggles].count = at - first - 3;"),
    M("gb-kept-at", "        g->kept = numKept;\n", "        g->kept = 0;\n"),
    M("gb-degenerate", "idx[g->first + j] = idx[g->first];",
      "idx[g->first + j] = idx[g->first + 1];"),
    M("gb-edit-remap", "    p            += (size_t)numRemap * sizeof(uint16_t);\n",
      "    p            += (size_t)numRemap;\n"),
    # -- the refresh
    M("gr-offset", "        off  += slice;\n", "        off  += slice + 16u;\n"),
    M("gr-nv", "|| slice < 8u || estripdata_num_verts(d) != nv",
      "|| slice < 8u || estripdata_num_verts(d) == nv"),
    M("gr-xyz", "            estripdata_get_xyz(d, v, &mesh->vbo[at].pos[0],\n"
      "                               &mesh->vbo[at].pos[1], "
      "&mesh->vbo[at].pos[2]);\n", ""),
    M("gr-colour", "            put_colour(&mesh->vbo[at], colour);\n", ""),
    M("gr-remap", "uint16_t at = e->remap[e->vertFirst[s] + v];",
      "uint16_t at = e->remap[e->vertFirst[s] + v / 2];"),
    M("gr-hidden", "if (geo_strip_flags(solid, g->strip, 0) & ESTRIP_HIDDEN) {",
      "if (geo_strip_flags(solid, g->strip, 0) & ESTRIP_SCUFFS) {"),
    M("gr-degenerate", "                ibo[j] = kept[0];\n",
      "                ibo[j] = kept[j];\n"),
    M("gr-show", "            memcpy(ibo, kept, (size_t)g->count * sizeof *ibo);\n",
      ""),
    M("gr-clusters", "            geocull_build(mesh->vbo[0].pos,\n"
      "                          (int)(sizeof(GeoRenderVertex) / sizeof(float)),\n"
      "                          mesh->ibo + b->first, b->count,\n"
      "                          clusters + b->cluster);\n", ""),
    M("gr-not-editable", "    if (e == NULL || mesh->vbo == NULL) {\n        return false;",
      "    if (mesh->vbo == NULL) {\n        return false;"),
    M("gr-free-edit",
      "    if (mesh->edit) {\n        block_free(mesh->edit);\n    }\n"
      "    memset(mesh, 0", "    memset(mesh, 0"),
]

EQUIVALENT = {
    "gr-free-edit":
        "A leak, which the harness cannot see: georender_free's memset "
        "clears the mesh either way, and the host's heap is not counted.",
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    args = files()
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        rc = mutpar.run_exe([exe] + args, out, 600)
        took = time.monotonic() - t0
        base = out.read_text(encoding="latin-1").splitlines()
        if rc != 0 or "faults 0" not in base:
            print("base already fails -- fix that before mutating")
            return 1
        print("base: %d lines, 0 faults" % len(base), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "geobake_test",
        lambda exe, out: mutpar.run_exe([exe] + args, out, limit),
        base, diff, EQUIVALENT, jobs)
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    args = ap.parse_args()
    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "out.txt"
        rc = mutpar.run_exe([exe] + files(), out, 600)
        lines = out.read_text(encoding="latin-1").splitlines()
    for ln in lines[-80:]:
        print(ln)
    sys.exit(1 if rc or "faults 0" not in lines else 0)


if __name__ == "__main__":
    main()
