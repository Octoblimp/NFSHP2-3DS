#!/usr/bin/env python3
"""Checks that the clusters geocull.c leaves out are ones no view shows.

TASKS 46 leaves unsent each 32 triangles of a batch whose box lies wholly
beyond one of the view's side planes (`3DS Files/source/geocull.h`). A box
it calls outside but whose triangles reach the view would be a hole in the
frame, so this builds geocull.c on the host (tools/src/geocull_test.c),
hands it strips of clusters in the shader checker's scenes
(geosolid_check.py), and runs every vertex through geosolid.v.pica on the
PICA's 24-bit floats, through that checker's interpreter.

  - Each box holds its vertices and no more, and a batch's box is its
    clusters' union; there are 1 + ceil(count / 96) of them.
  - Every box called OUT has its vertices beyond one plane, all of them,
    as the shader gives them on 24-bit floats, on 32-bit and exactly.
  - Every box called IN has its vertices inside, exactly.
  - Of the clusters plainly beyond a plane, most are called OUT, and the
    share of the triangles left unsent is printed.

Besides the strips in and around the view, each scene has clusters of one
point, put a hair beyond or within a plane in the clip space, where only
the margin keeps the PICA's rounding from bringing a vertex back.

    python tools/geocull_check.py            the check
    python tools/geocull_check.py --mutate   and each MUTATIONS edit of
                                             geocull.c must fail it
"""

import argparse
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geosolid_check as gs
import hostbuild

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files" / "source"
CULL_C = SRC / "geocull.c"
HARNESS = ROOT / "tools" / "src" / "geocull_test.c"
NL = chr(10)

CLUSTER = 96                    # GEO_CLUSTER_INDICES
STRIDE = 5                      # the harness's floats a vertex
OUT, PART, IN = 0, 1, 2

# Of the clusters whose vertices are all beyond one plane by this share of
# w, at least MIN_CULLED must be called OUT: a box's corner can reach past
# an oblique plane its vertices do not.
PLAIN = 0.01
MIN_CULLED = 0.5


# ============================================================== the strips

def view_points(s, rng, n, centre, radius):
    """`n` points round a view-space centre, in the model's space."""
    pts = centre + radius * rng.uniform(-1, 1, (n, 3))
    return pts


def to_model(s, view):
    inv = np.linalg.inv(s.mv)
    h = np.concatenate([view, np.ones((len(view), 1))], 1)
    return (inv @ h.T).T[:, :3]


def group_centre(s, rng, d_lim):
    d = s.near + (d_lim - s.near) * rng.uniform(0, 1) ** 2
    if rng.uniform(0, 1) < 0.08:
        d = -d * rng.uniform(0.01, 0.5)         # behind the eye
    x, y = rng.uniform(-1.9, 1.9, 2) * abs(d)
    return np.array([x, y, -d]), abs(d)


def boundary_points(s, rng, mvp64, n):
    """`n` clip-space points a hair beyond or within one of the side planes,
    in the model's space."""
    pts = []
    for _ in range(n):
        d = rng.uniform(s.near * 1.1, min(s.far, 3000.0))
        axis = int(rng.integers(0, 2))
        side = rng.choice([-1.0, 1.0])
        delta = 10 ** rng.uniform(-8, -1) * rng.choice([1, 1, 1, -1])
        c = np.zeros(4)
        c[axis] = side * d * (1 + delta)
        c[1 - axis] = rng.uniform(-0.95, 0.95) * d
        c[2] = s.proj[2, 2] * -d + s.proj[2, 3]
        c[3] = d
        m = np.linalg.solve(mvp64, c)
        pts.append(m[:3] / m[3])
    return np.array(pts)


def make_batches(s, rng):
    """A scene's batches: (vertices in the model's space, indices). Each is
    a strip, triangle t of vertices t, t+1, t+2, whose every 32 vertices
    lie round a centre of their own; neighbours share two."""
    mvp64 = s.proj @ s.mv
    d_lim = min(s.far, 3000.0)
    batches = []
    for b in range(7):
        groups = int(rng.integers(1, 41))
        tris = 32 * groups - int(rng.integers(0, 32))
        verts = []
        if b == 6:
            # Each group one point, repeated: its box is the point.
            pts = boundary_points(s, rng, mvp64, groups)
            for g in range(groups):
                n = 32 if g < groups - 1 else tris + 2 - 32 * g
                verts.append(np.repeat(pts[g:g + 1], n, 0))
        else:
            local = rng.uniform(0, 1) < 0.4
            if local:
                bc, bd = group_centre(s, rng, d_lim)
            for g in range(groups):
                n = 32 if g < groups - 1 else tris + 2 - 32 * g
                if local:
                    c = bc + rng.uniform(-1, 1, 3) * bd * 0.05
                    dist = bd
                else:
                    c, dist = group_centre(s, rng, d_lim)
                r = dist * 10 ** rng.uniform(-3, -0.5)
                verts.append(to_model(s, view_points(s, rng, n, c, r)))
        v = np.concatenate(verts).astype(np.float32)
        assert len(v) == tris + 2, (len(v), tris)
        t = np.arange(tris)
        idx = np.stack([t, t + 1, t + 2], 1).ravel()
        # Some batches index their vertices out of order.
        if rng.uniform(0, 1) < 0.3:
            perm = rng.permutation(len(v))
            inv = np.argsort(perm)
            v = v[perm]
            idx = inv[idx]
        batches.append((v, idx.astype(np.int64)))
    return batches


# ============================================================= the harness

def bits(x):
    return gs.bits(x)


def run_harness(exe, jobs):
    """geocull.c on each (mvp, batches) of `jobs`: per job, per batch, the
    boxes as (lo, hi, verdict)."""
    lines = []
    for mvp, batches in jobs:
        lines.append("P " + " ".join(bits(x) for x in mvp.ravel()))
        for v, idx in batches:
            pad = np.zeros((len(v), STRIDE), np.float32)
            pad[:, :3] = v
            pad[:, 3:] = 1e30               # what the build must skip
            lines.append("K %d %d %s %s" % (
                len(v), len(idx), " ".join(bits(x) for x in pad.ravel()),
                " ".join(str(int(i)) for i in idx)))
    r = subprocess.run([str(exe)], input=NL.join(lines) + NL,
                       capture_output=True, text=True, timeout=300)
    out = r.stdout.split(NL)
    res = []
    at = 0
    for mvp, batches in jobs:
        p = out[at].split()
        at += 1
        assert p and p[0] == "P", out[at - 1][:40]
        boxes = []
        for _ in batches:
            k = out[at].split()
            at += 1
            assert k and k[0] == "K", out[at - 1][:40]
            n = int(k[1])
            f = k[2:]
            assert len(f) == 7 * n, (n, len(f))
            bs = []
            for i in range(n):
                lo = np.array([gs.unbits(h) for h in f[7 * i:7 * i + 3]],
                              np.float32)
                hi = np.array([gs.unbits(h) for h in f[7 * i + 3:7 * i + 6]],
                              np.float32)
                bs.append((lo, hi, int(f[7 * i + 6])))
            boxes.append(bs)
        res.append(boxes)
    return res


# =============================================================== the check

def beyond(pos):
    """Each vertex's value at the four planes, x >= -w, x <= w, y >= -w,
    y <= w: (N, 4), negative beyond."""
    x, y, w = pos[:, 0], pos[:, 1], pos[:, 3]
    return np.stack([w + x, w - x, w + y, w - y], 1)


def check(exe, shbin, quiet=False):
    say = (lambda *a: None) if quiet else print
    code, ops, dvles = gs.parse(shbin)
    solid = dvles[0]
    scenes = [s for s in gs.make_scenes(46)
              if s.proj_kind in ("view", "envmap", "mirror")]
    helpers = gs.helper_outputs(exe["solid"], scenes)
    rng = np.random.default_rng(461)
    jobs = []
    for s, h in zip(scenes, helpers):
        jobs.append((h["mvp"], make_batches(s, rng)))
    results = run_harness(exe["cull"], jobs)

    faults = []
    stats = {"clusters": 0, "out": 0, "part": 0, "in": 0, "tris": 0,
             "tris_out": 0, "plain": 0, "plain_out": 0, "edge": 0,
             "edge_out": 0}
    for s, h, (mvp, batches), boxes in zip(scenes, helpers, jobs, results):
        un = gs.new_uniforms(solid, s, h)
        for bi, ((v, idx), bs) in enumerate(zip(batches, boxes)):
            where = "%s batch %d" % (s.name, bi)
            want = 1 + (len(idx) + CLUSTER - 1) // CLUSTER
            if len(bs) != want:
                faults.append("%s: %d boxes, not %d" % (where, len(bs), want))
                continue
            attrs = gs.make_vertices(s, rng, len(v))
            attrs[0] = np.zeros((len(v), 4), np.float32)
            attrs[0][:, :3] = v
            attrs[0][:, 3] = 1
            try:
                o24, c24 = gs.run(code, ops, solid, attrs, un, fp24=True)
                o32, c32 = gs.run(code, ops, solid, attrs, un)
            except gs.Unsupported as e:
                faults.append("%s: %s" % (where, e))
                continue
            p24 = gs.outputs(solid, o24, c24)[gs.OUT_POSITION]
            p32 = gs.outputs(solid, o32, c32)[gs.OUT_POSITION]
            h64 = np.concatenate([v.astype(np.float64),
                                  np.ones((len(v), 1))], 1)
            p64 = ((s.proj @ s.mv) @ h64.T).T
            b24, b32, b64 = beyond(p24), beyond(p32), beyond(p64)
            scale = np.abs(p64[:, 3]) + np.abs(p64[:, :2]).max(1)

            ranges = [(0, len(idx))] + [
                (c * CLUSTER, min((c + 1) * CLUSTER, len(idx)))
                for c in range(len(bs) - 1)]
            for ci, ((lo, hi, verdict), (a, b)) in enumerate(zip(bs, ranges)):
                name = "%s %s" % (where, "box" if ci == 0
                                  else "cluster %d" % (ci - 1))
                vi = idx[a:b]
                pv = v[vi]
                if not (np.array_equal(lo, pv.min(0))
                        and np.array_equal(hi, pv.max(0))):
                    faults.append("%s: box %s..%s, its vertices %s..%s"
                                  % (name, lo, hi, pv.min(0), pv.max(0)))
                if verdict not in (OUT, PART, IN):
                    faults.append("%s: verdict %d" % (name, verdict))
                    continue
                if verdict == OUT:
                    for tag, bv in (("24-bit", b24), ("32-bit", b32),
                                    ("exact", b64)):
                        if not (bv[vi] < 0).all(0).any():
                            near = bv[vi].min(0).max()
                            faults.append("%s: OUT, but on %s floats a "
                                          "vertex is inside every plane "
                                          "(%.3g)" % (name, tag, near))
                            break
                elif verdict == IN:
                    tol = -1e-5 * scale[vi][:, None]
                    if not (b64[vi] >= tol).all():
                        faults.append("%s: IN, but a vertex is beyond a "
                                      "plane" % name)
                if ci == 0:
                    continue
                stats["clusters"] += 1
                stats[("out", "part", "in")[verdict]] += 1
                stats["tris"] += (b - a) // 3
                if verdict == OUT:
                    stats["tris_out"] += (b - a) // 3
                plain = (b64[vi] < -PLAIN * scale[vi][:, None]).all(0).any()
                if plain:
                    stats["plain"] += 1
                    stats["plain_out"] += verdict == OUT
                if bi == 6:
                    stats["edge"] += 1
                    stats["edge_out"] += verdict == OUT
            # A batch called OUT is skipped whole, its clusters unasked.

    say("  %d scenes, %d clusters: %d out, %d across, %d in"
        % (len(scenes), stats["clusters"], stats["out"], stats["part"],
           stats["in"]))
    say("  %d of %d triangles left unsent (%.0f%%)"
        % (stats["tris_out"], stats["tris"],
           100.0 * stats["tris_out"] / max(stats["tris"], 1)))
    say("  of %d clusters plainly beyond a plane, %d called OUT; of %d one "
        "point a hair from a plane, %d"
        % (stats["plain"], stats["plain_out"], stats["edge"],
           stats["edge_out"]))
    if stats["plain_out"] < MIN_CULLED * stats["plain"]:
        faults.append("only %d of %d clusters plainly beyond a plane called "
                      "OUT" % (stats["plain_out"], stats["plain"]))
    if stats["in"] == 0 or stats["part"] == 0 or stats["out"] == 0:
        faults.append("a verdict never given: %s" % stats)
    return faults


# =============================================================== mutations

MUTATIONS = [
    ("no-margin", "#define GEOCULL_MARGIN 2e-4f", "#define GEOCULL_MARGIN 0.0f"),
    ("far-is-near", "far  += p[k] * c[f[k]];", "far  += p[k] * c[n[k]];"),
    ("far-corner-flipped", "out->farAt[i][j]  = (uint8_t)(up ? 3 + j : j);",
     "out->farAt[i][j]  = (uint8_t)(up ? j : 3 + j);"),
    ("z-for-w", "out->pl[i][j]  = mvp[3][j]", "out->pl[i][j]  = mvp[2][j]"),
    ("no-near-test", "part |= 1u << i;", "part |= 0;"),
    ("across-wrong-plane", "part |= 1u << i;", "part |= 1u << (i ^ 1);"),
    ("cluster-skips-first", "int first = (c - 1) * GEO_CLUSTER_INDICES;",
     "int first = (c - 1) * GEO_CLUSTER_INDICES + 1;"),
    ("union-lo-only", "box_add(&out[0], out[c].hi);", ""),
    ("count-floors", "1 + (count + GEO_CLUSTER_INDICES - 1) / GEO_CLUSTER_INDICES",
     "1 + count / GEO_CLUSTER_INDICES"),
    ("signed-sizes", "fabsf(mvp[3][j]) + fabsf(mvp[row[i]][j])",
     "-(fabsf(mvp[3][j]) + fabsf(mvp[row[i]][j]))"),
]


def build_all(tmp, cull_src=None):
    exe = {"solid": None, "cull": None}
    exe["solid"], shbin = gs.build_all(tmp)
    exe["cull"] = hostbuild.build(tmp, [str(HARNESS), str(cull_src or CULL_C)],
                                  name="geocull_test", quiet=True)
    return exe, shbin


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    args = ap.parse_args()
    np.seterr(all="ignore")
    with tempfile.TemporaryDirectory() as tmp:
        exe, shbin = build_all(tmp)
        faults = check(exe, shbin)
        for f in faults[:20]:
            print("  FAULT " + f)
        if faults:
            print("geocull_check: %d faults" % len(faults))
            return 1
        print("geocull_check: 0 faults")
        if not args.mutate:
            return 0
        caught = 0
        text = CULL_C.read_bytes().decode("utf-8")
        for name, old, new_text in MUTATIONS:
            if text.count(old) != 1:
                print("  %s: PATTERN NOT FOUND" % name)
                continue
            mdir = Path(tmp) / name
            mdir.mkdir()
            copy = mdir / CULL_C.name
            copy.write_bytes(text.replace(old, new_text).encode("utf-8"))
            exe_m = dict(exe)
            exe_m["cull"] = hostbuild.build(
                mdir, [str(HARNESS), str(copy)], name="geocull_test",
                quiet=True)
            f = check(exe_m, shbin, quiet=True)
            caught += bool(f)
            print("  %s: %s" % (name, "caught (%s)" % f[0][:110] if f
                                else "NOT CAUGHT"))
        print("geocull_check: %d of %d mutations caught"
              % (caught, len(MUTATIONS)))
        return 0 if caught == len(MUTATIONS) else 1


if __name__ == "__main__":
    sys.exit(main())
