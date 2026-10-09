#!/usr/bin/env python3
"""Cross-check 3DS Files/source/epositionmarker.c's loader and unloader,
LoaderPositionMarkers (0x001a7e90) and UnloaderPositionMarkers
(0x001a7f08), against the retail image, SLES_507.31, run in mipsemu.

**The model** is retail's own code: the loader, the unloader and
eFindPositionMarker (0x001a7f78), over PositionMarkerList (gp-19328),
which the script empties as retail's static constructor does. The harness
(tools/src/positionmarker_test.c) runs epositionmarker.c and prints the
same lines. eFindPositionMarker has its own check in
carrenderinfo_check.py; here it walks what the loader linked.

**The layouts.** The script lays each chunk out as the disc does: the
type, the size, the pad up to 16 and the 32-byte records, then a tail
short of a record. The host has 8-byte pointers, so the harness rebuilds
the records at the host's size after the same pad, with a size word that
gives the same count. A record prints as kK.I, chunk K's I-th, the head
as H, NULL as 0, anything else as ?.

**Compared**: each call's answer, the list forward by next and back by
prev after it, the records' fields, and the searches over the list.

**The script**: the guard on the type's neighbours; one chunk at each of
the four word misalignments, with 0 to 7 records and tails of 0 to 31
bytes, loaded and unloaded; random loads and unloads over eight chunks
with names and types shared between them, and searches from heads and
from linked records; and every position-marker chunk of the retail disc
(the cars' GEOMETRY.BINs), loaded together, searched by every type and
name, unloaded out of order and loaded again.

Not scripted: a size short of the pad, whose count wraps to 2^27 and
walks off the chunk in retail as in the port.

    python tools/positionmarker_check.py
    python tools/positionmarker_check.py --mutate [--only a,b]
"""
import argparse
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/positionmarker_test.c"
EPC = "3DS Files/source/epositionmarker.c"
SOURCES = [HARNESS, EPC]
HARNESS_TIMEOUT = 60
DISC = ROOT / "extracted-retail"

GP = retail_model.RETAIL_GP
LIST = GP - 19328                       # PositionMarkerList
F_LOAD = 0x001a7e90
F_UNLOAD = 0x001a7f08
F_FIND = 0x001a7f78
PM_ID = 0x00034013
REC = 32


# ================================================================== model

class Model(object):
    def __init__(self):
        self.e = retail_model.RetailEmu(ieee=True, eediv=True, eesqrt=True)
        self.out = []
        self.reset()

    def emit(self, line):
        self.out.append(line)

    def reset(self):
        e = self.e
        e.put32(LIST, LIST)
        e.put32(LIST + 4, LIST)
        self.cp, self.data, self.nrec = {}, {}, {}

    def total(self):
        return sum(self.nrec.values())

    def label(self, v):
        v &= M32
        if v == 0:
            return "0"
        if v == LIST:
            return "H"
        for k, d in self.data.items():
            if d <= v < d + REC * self.nrec[k] and (v - d) % REC == 0:
                return "k%d.%d" % (k, (v - d) // REC)
        return "?"

    def dump(self):
        e = self.e
        limit = self.total() + 2
        for name, off in (("list", 0), ("back", 4)):
            parts = []
            n, steps = e.u32(LIST + off), 0
            while n != LIST and steps < limit:
                lb = self.label(n)
                parts.append(lb)
                if lb in ("?", "0"):
                    break
                n = e.u32(n + off)
                steps += 1
            self.emit("  %s%s" % (name, "".join(" " + p for p in parts)))

    def run(self, a):
        e = self.e
        o = a[0]
        if o == "reset":
            self.reset()
            self.emit("reset")
        elif o == "chunk":
            k, mis, typ, n, rem, fill = (int(x, 0) for x in a[1:7])
            p = e.alloc(64 + REC * n + rem + 64, align=16)
            e.write(p, bytes([fill]) * (64 + REC * n + rem + 64))
            c = p + mis
            data = (c + 23) & ~15
            e.put32(c, typ)
            e.put32(c + 4, data - (c + 8) + REC * n + rem)
            self.cp[k], self.data[k], self.nrec[k] = c, data, n
        elif o == "rec":
            k, i = int(a[1]), int(a[2])
            m = self.data[k] + REC * i
            for j, w in enumerate(a[3:11]):
                e.put32(m + 4 * j, int(w, 0))
        elif o in ("load", "unload"):
            k = int(a[1])
            r = e.call(F_LOAD if o == "load" else F_UNLOAD, self.cp[k])
            self.emit("%s k%d -> %d" % (o, k, r))
            self.dump()
        elif o == "dump":
            self.emit("dump")
            self.dump()
        elif o == "fields":
            k = int(a[1])
            self.emit("fields k%d" % k)
            for i in range(self.nrec[k]):
                m = self.data[k] + REC * i
                self.emit("  k%d.%d %s" % (k, i, " ".join(
                    "%08x" % e.u32(m + off) for off in (8, 12, 16, 20, 24,
                                                         28))))
        elif o == "find":
            name, typ = int(a[1], 0), int(a[2], 0)
            prev = 0
            if a[3] != "0":
                k, i = (int(x) for x in a[3][1:].split("."))
                prev = self.data[k] + REC * i
            r = e.call(F_FIND, s32(name), s32(typ), s32(prev))
            self.emit("find %s %s %s -> %s" % (a[1], a[2], a[3],
                                               self.label(r)))
        else:
            raise ValueError(o)


def model(lines):
    m = Model()
    for ln in lines:
        m.run(ln.split("|"))
    return m.out


# ================================================================ the script

def H(v):
    return "0x%08x" % (v & M32)


class Script(object):
    """The ops, and the list as retail keeps it, so that a search starts
    only from a record that is on it."""

    def __init__(self):
        self.lines = []
        self.reset()

    def op(self, *a):
        self.lines.append("|".join(str(x) for x in a))

    def reset(self):
        self.op("reset")
        self.recs = {}          # k -> [(name, type)]
        self.ok = {}            # k -> whether the type is the loader's
        self.linked = []        # (k, i) in list order
        self.loaded = set()

    def chunk(self, k, mis, recs, rem=0, typ=PM_ID, fill=0xa5, words=None):
        self.op("chunk", k, mis, H(typ), len(recs), rem, fill)
        for i, (nm, ty) in enumerate(recs):
            w = words[i] if words else (0x11111111 * (i % 15 + 1), 0x0,
                                        nm, ty, 0x3f800000 + i,
                                        0xc1200000 + k, 0x40400000 + 7 * i,
                                        (k << 16) | (i << 8) | 3)
            self.op("rec", k, i, *(H(x) for x in w))
        self.recs[k] = list(recs)
        self.ok[k] = typ == PM_ID

    def load(self, k):
        self.op("load", k)
        if self.ok[k]:
            self.linked += [(k, i) for i in range(len(self.recs[k]))]
            self.loaded.add(k)

    def unload(self, k):
        self.op("unload", k)
        if self.ok[k]:
            self.linked = [r for r in self.linked if r[0] != k]
            self.loaded.discard(k)

    def find(self, name, typ, prev=None):
        self.op("find", H(name), H(typ),
                "0" if prev is None else "k%d.%d" % prev)

    def findall(self, name, typ):
        """A search from the head and on from each hit, as a caller walks
        them, plus one from each linked record."""
        hits = [r for r in self.linked
                if (name and self.recs[r[0]][r[1]][0] == name
                    and (typ == 0 or self.recs[r[0]][r[1]][1] == typ))
                or (not name and self.recs[r[0]][r[1]][1] == typ)]
        if name == 0 and typ == 0:
            hits = []
        self.find(name, typ)
        for h in hits:
            self.find(name, typ, h)


def guard_cases(sc):
    for typ in (PM_ID - 1, PM_ID + 1, PM_ID ^ 0x80000000, PM_ID ^ 0x100,
                PM_ID ^ 0x10000, 0, 0xffffffff, 0x00034014, 0x80034013):
        sc.reset()
        sc.chunk(0, 0, [(0x100, 0x200), (0x101, 0x200)], typ=typ)
        sc.load(0)
        sc.unload(0)
        sc.op("dump")
        sc.op("fields", 0)


def single_cases(sc):
    for mis in (0, 4, 8, 12):
        for n in (0, 1, 2, 3, 7):
            for rem in (0, 1, 4, 16, 31):
                sc.reset()
                recs = [(0x1000 + i, 0x2000 + (i & 1)) for i in range(n)]
                sc.chunk(1, mis, recs, rem=rem, fill=(mis * 16 + rem) & 0xff)
                sc.load(1)
                sc.op("fields", 1)
                sc.findall(0, 0x2000)
                sc.findall(0x1001, 0)
                sc.findall(0x1001, 0x2001)
                sc.findall(0x1001, 0x2000)
                sc.findall(0, 0)
                sc.unload(1)
                sc.op("fields", 1)
                sc.find(0, 0x2000)


def random_cases(sc, rng):
    names = [0x5a5a0000 + i for i in range(6)] + [0x80000001, 0xffffffff]
    types = [0x7e000000 + i for i in range(3)] + [0x9abcdef0]
    for run in range(60):
        sc.reset()
        for k in range(8):
            n = rng.choice((0, 1, 1, 2, 3, 4, 6))
            recs = [(rng.choice(names), rng.choice(types)) for _ in range(n)]
            sc.chunk(k, rng.choice((0, 4, 8, 12)), recs,
                     rem=rng.choice((0, 0, 3, 31)),
                     typ=PM_ID if rng.random() < 0.9 else PM_ID + 1)
        for step in range(30):
            k = rng.randrange(8)
            if k in sc.loaded:
                sc.unload(k)
            else:
                sc.load(k)
            r = rng.random()
            if r < 0.3:
                sc.findall(0, rng.choice(types))
            elif r < 0.5:
                sc.findall(rng.choice(names), 0)
            elif r < 0.7:
                sc.findall(rng.choice(names), rng.choice(types))
            elif r < 0.75 and sc.linked:
                sc.find(rng.choice(names), rng.choice(types),
                        rng.choice(sc.linked))
        for k in sorted(sc.loaded):
            sc.unload(k)
        sc.op("dump")


def disc_chunks():
    """Every 0x34013 chunk at the top of a retail file: (file, the chunk's
    offset mod 16, its tail past the records, its records' eight words)."""
    out = []
    for p in sorted(DISC.rglob("*")):
        if not p.is_file() or p.suffix.upper() not in (".BIN", ".BUN"):
            continue
        d = p.read_bytes()
        pos = 0
        while pos + 8 <= len(d):
            t, s = struct.unpack_from("<II", d, pos)
            if t == PM_ID:
                data = (pos + 23) & ~15
                left = s - (data - (pos + 8))
                n, rem = left // REC, left % REC
                words = [struct.unpack_from("<8I", d, data + REC * i)
                         for i in range(n)]
                out.append((p.relative_to(DISC).as_posix(), pos % 16, rem,
                            words))
            pos += 8 + s
    return out


def disc_cases(sc, rng):
    chunks = disc_chunks()
    if len(chunks) < 40:
        sys.exit("only %d position-marker chunks under %s" % (len(chunks),
                                                              DISC))
    sc.reset()
    for k, (_, mis, rem, words) in enumerate(chunks):
        sc.chunk(k, mis, [(w[2], w[3]) for w in words], rem=rem, fill=0,
                 words=words)
    for k in range(len(chunks)):
        sc.load(k)
    allrecs = [r for k in range(len(chunks)) for r in sc.recs[k]]
    for ty in sorted({t for _, t in allrecs}):
        sc.findall(0, ty)
    for nm in sorted({n for n, _ in allrecs}):
        sc.findall(nm, 0)
    for nm, ty in sorted(set(allrecs))[::7]:
        sc.findall(nm, ty)
    order = list(range(len(chunks)))
    rng.shuffle(order)
    for k in order[:len(order) // 2]:
        sc.unload(k)
    for ty in sorted({t for _, t in allrecs})[::3]:
        sc.findall(0, ty)
    for k in order[:len(order) // 4]:
        sc.load(k)
    for k in order:
        if k in sc.loaded:
            sc.unload(k)
    sc.op("dump")
    for k in range(0, len(chunks), 5):
        sc.op("fields", k)


def script():
    sc = Script()
    guard_cases(sc)
    single_cases(sc)
    random_cases(sc, random.Random(0x34013))
    disc_cases(sc, random.Random(0x1a7e90))
    return sc.lines


# ================================================================= running

def build_harness(tmp, name="positionmarker_test"):
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


def write_inputs(d):
    lines = script()
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return lines, sc


# ============================================================= mutations

P = EPC
LINK = """        last->next = &m->Node;
        PositionMarkerList.prev = &m->Node;
        m->Node.prev = last;
        m->Node.next = &PositionMarkerList;"""
MUTATIONS = [
    ("ld_guard", P, "        return 0;\n    m = first_marker(chunk, &n);\n"
     "    for (i = 0;", "        ;\n    m = first_marker(chunk, &n);\n"
     "    for (i = 0;"),
    ("ul_guard", P, "        return 0;\n    m = first_marker(chunk, &n);\n"
     "    for (; n", "        ;\n    m = first_marker(chunk, &n);\n"
     "    for (; n"),
    ("id", P, "#define POSITION_MARKERS_ID 0x00034013u",
     "#define POSITION_MARKERS_ID 0x00034012u"),
    ("id_high", P, "#define POSITION_MARKERS_ID 0x00034013u",
     "#define POSITION_MARKERS_ID 0x80034013u"),
    ("pad_15", P, "(uintptr_t)chunk + 23u", "(uintptr_t)chunk + 15u"),
    ("pad_31", P, "(uintptr_t)chunk + 23u", "(uintptr_t)chunk + 31u"),
    ("pad_8", P, "(uintptr_t)chunk + 23u) & ~(uintptr_t)15u",
     "(uintptr_t)chunk + 23u) & ~(uintptr_t)7u"),
    ("cnt_nopad", P, "    *n = (bchunk_u32(chunk + 4) - (uint32_t)(data - "
     "(chunk + 8)))", "    *n = (bchunk_u32(chunk + 4))"),
    ("cnt_from_c", P, "(uint32_t)(data - (chunk + 8))",
     "(uint32_t)(data - chunk)"),
    ("cnt_size_at_8", P, "bchunk_u32(chunk + 4)", "bchunk_u32(chunk + 8)"),
    ("cnt_round_up", P, "         / (uint32_t)sizeof(ePositionMarker);",
     "         / (uint32_t)sizeof(ePositionMarker) + 1u;"),
    ("ld_le", P, "for (i = 0; i < n; i++, m++)",
     "for (i = 0; i <= n; i++, m++)"),
    ("ld_skip_last", P, "for (i = 0; i < n; i++, m++)",
     "for (i = 1; i < n; i++, m++)"),
    ("ld_no_step", P, "for (i = 0; i < n; i++, m++)",
     "for (i = 0; i < n; i++)"),
    ("ld_no_tail_next", P, "        last->next = &m->Node;\n", ""),
    ("ld_no_list_prev", P, "        PositionMarkerList.prev = &m->Node;\n",
     ""),
    ("ld_prev_head", P, "        m->Node.prev = last;",
     "        m->Node.prev = &PositionMarkerList;"),
    ("ld_next_null", P, "        m->Node.next = &PositionMarkerList;",
     "        m->Node.next = NULL;"),
    ("ld_at_head", P, LINK, """        bNode *first = PositionMarkerList.next;

        (void)last;
        first->prev = &m->Node;
        PositionMarkerList.next = &m->Node;
        m->Node.next = first;
        m->Node.prev = &PositionMarkerList;"""),
    ("ld_ret0", P, "        m->Node.next = &PositionMarkerList;\n    }\n"
     "    return 1;", "        m->Node.next = &PositionMarkerList;\n    }\n"
     "    return 0;"),
    ("ul_ret0", P, "        next->prev = prev;\n    }\n    return 1;",
     "        next->prev = prev;\n    }\n    return 0;"),
    ("ul_no_prev_next", P, "        prev->next = next;\n", ""),
    ("ul_no_next_prev", P, "        next->prev = prev;\n", ""),
    ("ul_prev_self", P, "        prev->next = next;",
     "        prev->next = prev;"),
    ("ul_skip_last", P, "for (; n != 0; n--, m++)", "for (; n > 1; n--, m++)"),
    ("ul_no_step", P, "for (; n != 0; n--, m++)", "for (; n != 0; n--)"),
    ("ul_from_list", P, "        bNode *next = m->Node.next, "
     "*prev = m->Node.prev;", "        bNode *next = m->Node.next, "
     "*prev = PositionMarkerList.prev;"),
]

EQUIVALENT = {
}


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    indir = tempfile.TemporaryDirectory()
    lines, scp = write_inputs(indir.name)
    base_lines = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base_lines, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "positionmarker_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base_lines, diff, EQUIVALENT, jobs)
    indir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))

    with tempfile.TemporaryDirectory() as tmp:
        lines, scp = write_inputs(tmp)
        got = model(lines)
        exe = build_harness(tmp)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
