#!/usr/bin/env python3
"""Cross-check eenvmap.c's sphere map sample table against the retail image,
run in mipsemu.

The model is the image: CreateRefSampleTable (0x00117a38) and
ComputeReflectionST (0x001179b0) run as shipped, with bNormalize (the
bVector2 one) and the VU0 macro code under them, and nothing stubbed. The
harness (tools/src/envsample_test.c) runs eenvmap.c's
create_ref_sample_table and compute_reflection_st, with bvector.c's
bNormalize2, and prints the same lines.

The script:

    F p             fill the table, all ten 7 by 7 grids, with the byte p
    T               build the table, then dump every sample, the unwritten
                    rows and columns too, word for word
    S x y z w       ComputeReflectionST on the vector's four lanes: the
                    vector after, all four lanes, and s and t

The table is built over a fill and over zeros, so a sample either side
leaves alone shows. The vectors are the table's own 216 directions, the
six axes but -z, and 300 at random, short and long, but none within a
degree of -z, where the sphere map's formula divides by nothing.

Checked against the image, not diffed: eInitEnvMap's first call is
CreateRefSampleTable; the table's base and the two constants are where
the checker reads them; and one build calls ComputeReflectionST 216 times
and bNormalize 24.

    python tools/envsample_check.py
    python tools/envsample_check.py --mutate [--only a,b]
    python tools/envsample_check.py --dump out/envsample
"""
import argparse
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
import physicscar_check as pcc
import retail_model

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/envsample_test.c"
EMC = "3DS Files/source/eenvmap.c"
SOURCES = [HARNESS, EMC, "3DS Files/source/bvector.c",
           "3DS Files/source/bmath.c", "3DS Files/source/bmathtab.c"]
HARNESS_TIMEOUT = 30

# ================================================================ the image

GP = 0x003358f0
CREATE = 0x00117a38             # CreateRefSampleTable__Fv
REFLECT = 0x001179b0            # ComputeReflectionST__FP8bVector3P8bVector2
NORMALIZE = 0x002588a0          # bNormalize__FP8bVector2PC8bVector2
INIT = 0x00117508               # eInitEnvMap__Fv
TABLE = 0x002d7130
GRIDS, SIDE, SAMPLE = 10, 7, 28
TABLE_SIZE = GRIDS * SIDE * SIDE * SAMPLE
VEC = 0x01000000
ST = 0x01000040


def fbits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def bfloat(u):
    return struct.unpack("<f", struct.pack("<I", u))[0]


def table_dirs():
    """The 216 directions CreateRefSampleTable takes, as float32 bits."""
    out = []
    for f in range(6):
        for r in range(6):
            for c in range(6):
                a = bfloat(fbits(bfloat(fbits(0.4)) * r))
                b = bfloat(fbits(bfloat(fbits(0.4)) * c))
                d = [(a - 1, b - 1, 1), (1, b - 1, 1 - a), (1 - a, b - 1, -1),
                     (-1, b - 1, a - 1), (a - 1, -1, b - 1),
                     (a - 1, 1, 1 - b)][f]
                out.append(tuple(fbits(v) for v in d) + (0,))
    return out


def script():
    rng = random.Random(0x5eed)
    ops = ["F a5", "T", "F 00", "T", "F ff", "T"]
    vecs = table_dirs()
    for ax in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1),
               (0, 0, 2.5), (3, 0, 0)):
        vecs.append(tuple(fbits(v) for v in ax) + (0,))
    while len(vecs) < 216 + 7 + 300:
        scale = rng.choice((1e-3, 0.5, 1.0, 7.0, 1e4))
        v = [rng.uniform(-1, 1) * scale for _ in range(3)]
        n = math.sqrt(sum(x * x for x in v))
        if n == 0 or v[2] / n < -0.99985:
            continue
        w = rng.choice((0.0, 1.0, -2.0, rng.uniform(-5, 5)))
        vecs.append(tuple(fbits(x) for x in v) + (fbits(w),))
    for v in vecs:
        ops.append("S %08x %08x %08x %08x" % v)
    return ops


def encode(ops):
    return NL.join(ops) + NL


class Model(object):
    def __init__(self):
        self.e = retail_model.emu(retail=True, ieee=True)
        self.calls = {}

    def count(self, addr):
        def hook(e):
            self.calls[addr] = self.calls.get(addr, 0) + 1
        return hook

    def dump(self):
        out = []
        raw = self.e.read(TABLE, TABLE_SIZE)
        for s in range(GRIDS * SIDE * SIDE):
            w = struct.unpack_from("<7I", raw, s * SAMPLE)
            out.append("T %d %d %d %s" % (s // 49, s // 7 % 7, s % 7,
                                          " ".join("%08x" % x for x in w)))
        return out

    def run(self, ops):
        e = self.e
        out = []
        for op in ops:
            if op.startswith("F "):
                p = int(op[2:], 16)
                e.write(TABLE, bytes([p]) * TABLE_SIZE)
                out.append("F %02x" % p)
            elif op == "T":
                e.hooks = {REFLECT: self.count(REFLECT),
                           NORMALIZE: self.count(NORMALIZE)}
                self.calls = {}
                e.call(CREATE)
                e.hooks = {}
                self.table_calls = dict(self.calls)
                out.extend(self.dump())
            elif op.startswith("S "):
                v = [int(x, 16) for x in op[2:].split()]
                e.write(VEC, struct.pack("<4I", *v))
                e.write(ST, b"\xa5" * 8)
                e.call(REFLECT, VEC, ST)
                d = struct.unpack("<4I", e.read(VEC, 16))
                st = struct.unpack("<2I", e.read(ST, 8))
                out.append("S %s -> %s" % (
                    " ".join("%08x" % x for x in v),
                    " ".join("%08x" % x for x in d + st)))
        return out


def image_facts(m):
    """What the port takes from the image without running it."""
    e = m.e
    out = []
    jal = 0x0c000000 | (CREATE >> 2)
    first = None
    for a in range(INIT, INIT + 0x40, 4):
        if e.u32(a) >> 26 == 3:
            first = a
            break
    out.append((first is not None and e.u32(first) == jal,
                "eInitEnvMap's first call: %s" % (
                    "%08x at %08x" % (e.u32(first), first) if first else
                    "none")))
    step = bfloat(e.u32(GP - 32464))
    spread = bfloat(e.u32(GP - 32460))
    out.append((fbits(step) == fbits(0.4), "gp-32464 = %r" % step))
    out.append((fbits(spread) == fbits(0.16), "gp-32460 = %r" % spread))
    # lui 0x002d ; addiu 28976: the face grids' base, in the build's loop.
    out.append((e.u32(0x00117bd8) == 0x26c47130,
                "the table's base: %08x" % e.u32(0x00117bd8)))
    calls = getattr(m, "table_calls", {})
    out.append((calls.get(REFLECT) == 216 and calls.get(NORMALIZE) == 24,
                "one build: ComputeReflectionST %d, bNormalize %d" % (
                    calls.get(REFLECT, 0), calls.get(NORMALIZE, 0))))
    return out


def model(ops):
    m = Model()
    lines = m.run(ops)
    return m, lines


# ============================================================== the harness

def build_harness(tmp, name="envsample_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return pcc.HARNESS_HUNG
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


diff = pcc.diff

# ============================================================ the mutations

MUTATIONS = [
    ("rsq-skips-z", EMC,
     "q = 1.0f / sqrtf((d->x * d->x + d->y * d->y) + d->z * d->z);",
     "q = 1.0f / sqrtf(d->x * d->x + d->y * d->y);"),
    ("pad-not-scaled", EMC,
     "    d->pad *= q;\n", "\n"),
    ("st-plus-z-dropped", EMC,
     "    z = d->z + 1.0f;", "    z = d->z;"),
    ("st-not-doubled", EMC,
     "    m = m + m;", "    m = m;"),
    ("st-swapped", EMC,
     "    st->y = y / m + 0.5f;\n    st->x = x / m + 0.5f;",
     "    st->y = x / m + 0.5f;\n    st->x = y / m + 0.5f;"),
    ("st-no-half", EMC,
     "    st->x = x / m + 0.5f;", "    st->x = x / m;"),
    ("step-0.5", EMC,
     "#define SAMPLE_STEP   0.4f", "#define SAMPLE_STEP   0.5f"),
    ("spread-0.2", EMC,
     "#define SAMPLE_SPREAD 0.16f", "#define SAMPLE_SPREAD 0.2f"),
    ("face1-z-sign", EMC,
     "d.x = 1.0f, d.y = b + -1.0f, d.z = 1.0f - a;",
     "d.x = 1.0f, d.y = b + -1.0f, d.z = a + -1.0f;"),
    ("face2-x-sign", EMC,
     "d.x = 1.0f - a, d.y = b + -1.0f, d.z = -1.0f;",
     "d.x = a + -1.0f, d.y = b + -1.0f, d.z = -1.0f;"),
    ("face5-y-sign", EMC,
     "d.x = a + -1.0f, d.y = 1.0f, d.z = 1.0f - b;",
     "d.x = a + -1.0f, d.y = -1.0f, d.z = 1.0f - b;"),
    ("dir-normalised-stored", EMC,
     "                e->x = d.x;\n                e->y = d.y;\n"
     "                e->z = d.z;\n                compute_reflection_st(&d, &st);",
     "                compute_reflection_st(&d, &st);\n"
     "                e->x = d.x;\n                e->y = d.y;\n"
     "                e->z = d.z;"),
    ("uv-swapped", EMC,
     "                e->u = a * 0.5f;\n                e->v = b * 0.5f;",
     "                e->u = b * 0.5f;\n                e->v = a * 0.5f;"),
    ("faces-only-five", EMC,
     "    for (f = 0; f < 6; f++) {\n        for (r = 0; r < 6; r++) {",
     "    for (f = 0; f < 5; f++) {\n        for (r = 0; r < 6; r++) {"),
    ("grid-writes-row-6", EMC,
     "        for (r = 0; r < 6; r++) {\n            for (c = 0; c < 6; c++) {",
     "        for (r = 0; r < 7; r++) {\n            for (c = 0; c < 6; c++) {"),
    ("back-centre-after-normalise", EMC,
     "    cs  = n.x + 0.5f;\n    ct  = n.y + 0.5f;\n    bNormalize2(&n, &n);",
     "    bNormalize2(&n, &n);\n    cs  = n.x + 0.5f;\n    ct  = n.y + 0.5f;"),
    ("back-no-half", EMC,
     "    hx = n.x * 0.5f;", "    hx = n.x;"),
    ("back-spread-order", EMC,
     "        row[c].s = cs + hx * w * SAMPLE_SPREAD;",
     "        row[c].s = cs + hx * (w * SAMPLE_SPREAD);"),
    ("back-w-over-6", EMC,
     "        float w = (float)c / 5.0f;", "        float w = (float)c / 6.0f;"),
    ("back-6-from-face-3", EMC,
     "back_row(T[6][r], &T[4][r][0],", "back_row(T[6][r], &T[3][r][0],"),
    ("back-7-from-row-0", EMC,
     "back_row(T[7][r], &T[1][5][r],", "back_row(T[7][r], &T[1][0][r],"),
    ("back-8-v-rises", EMC,
     "k1, 0.5f - k1, 1.0f, -0.5f);", "k1, 0.5f - k1, 1.0f, 0.5f);"),
    ("back-9-u-from-0", EMC,
     "back_row(T[9][r], &T[3][0][r], 1.0f, -0.5f, k, 0.5f - k);",
     "back_row(T[9][r], &T[3][0][r], 0.0f, 0.5f, k, 0.5f - k);"),
    ("back-k-over-6", EMC,
     "        float k  = (float)r / 5.0f;", "        float k  = (float)r / 6.0f;"),
    ("init-skips-table", EMC,
     "    create_ref_sample_table();\n    for (i = 0; i < 6; i++) {",
     "    for (i = 0; i < 6; i++) {"),
]

# Mutations that survive because they change nothing the image can tell.
# init-skips-table: the harness never calls eenvmap_init (its views and
# targets are not this checker's); the image fact above checks the call.
EQUIVALENT = {"init-skips-table"}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    _m, base = model(sc)
    caught, survived, missing, equivalent = 0, [], [], []
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "script.txt"
    scp.write_text(encode(sc))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel, before, after = m
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-44s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-44s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-44s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-44s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-44s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))
    scdir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    ran = {m[0] for m in todo}
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (n in ran or only is None)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
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
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None))

    sc = script()
    m, lines = model(sc)
    facts = image_facts(m)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "script.txt"
        scp.write_text(encode(sc))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)
        d.with_suffix(".image").write_text(
            NL.join(("   " if ok else "BAD") + " " + l for ok, l in facts) + NL)

    bad = [l for ok, l in facts if not ok]
    for l in bad:
        print("image: " + l)
    n = diff(lines, harness)
    print("image: %d facts, %d wrong" % (len(facts), len(bad)))
    print("%d steps, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc or bad) else 0)


if __name__ == "__main__":
    main()
