#!/usr/bin/env python3
"""Mutation passes out of the tree and in parallel, and the model cached.

A checker's --mutate used to write each mutant into `3DS Files/source`,
build, run, and put the original back, one mutant at a time. That had two
costs. A pass of 273 mutants took most of an hour, and for all of it
nothing else could be built: a build, or even a read of the source, saw
whichever mutant was in flight.

Here the pass first copies what its build reads -- the sources, and
every header in `3DS Files/source` and beside each source -- into a
snapshot, and compiles the snapshot once. Each mutant is built from the
snapshot, never from the tree, so the tree is never touched, and an edit
made to it while a pass runs reaches no mutant. The snapshot's own build
must give the base transcript, or the pass stops. Up to JOBS mutants
build and run at once, and the lines are printed in the pass's order,
each as soon as it and those before it are done.

A mutant of a source is that file, mutated, under its own name in a
temporary directory: it compiles alone, with the snapshot's copy of its
directory and of `3DS Files/source` as the include path, so its quoted
includes find what they found beside the original. It links with the
snapshot's other objects. A mutant of a header is a copy of the whole
snapshot with the header mutated, every source compiled again. Only a
mutation of a file the snapshot has no copy of goes in place, as before,
after the rest, with hostbuild.write_source's backup.

The model -- retail's code run in mipsemu over the script -- is the slow
half of a check: seven minutes for car select. Its transcript is a
function of the script, the Python that ran it and the data it read, so
model_cached keeps it under a key made of all three: the script's lines,
every module loaded from tools/ but this one and hostbuild, the retail
ELF, and the data files the checker names, with any file a script line
names. Of the checker itself only what comes before its `cut`
line counts, so that its mutations and its list of equivalents, which
come after, can change without a seven-minute rerun. Set
NFSHP2_NO_MODEL_CACHE=1 to run the model anyway.
"""
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import hostbuild

ROOT = hostbuild.ROOT
TOOLS = ROOT / "tools"
NL = chr(10)
JOBS = max(1, min(16, os.cpu_count() or 4))
ELF = ROOT / "PS2 Files" / "Full Game" / "SLES_507.31"
MODEL_CACHE = Path(os.environ.get("NFSHP2_MODEL_CACHE")
                   or Path(tempfile.gettempdir()) / "nfshp2-model-cache")
HUNG = -9999
# Modules of tools/ that the model never runs: the pass's own machinery.
NOT_THE_MODEL = ("mutpar.py", "hostbuild.py")
CRASHED = -9998


# ------------------------------------------------------------ the model

def _checker_text(p, cut):
    """The checker's source up to its first `cut` line."""
    text = p.read_bytes()
    if cut:
        i = text.find(cut.encode())
        if i >= 0:
            return text[:i]
    return text


def _script_text(lines):
    """The script as one string: its lines, or the repr of a script that
    is not a list of strings (selcam's are tuples)."""
    if all(isinstance(x, str) for x in lines):
        return NL.join(lines)
    return repr(lines)


def _named_files(text):
    """The files the script names, as carsel's `load|<path>` does."""
    seen = set()
    for tok in re.split(r"[\s|,'\"()\[\]]+", text):
        if ("/" in tok or chr(92) in tok) and len(tok) < 260:
            seen.add(tok)
    return sorted(Path(t) for t in seen if Path(t).is_file())


def _model_key(lines, data, cut):
    main = getattr(sys.modules.get("__main__"), "__file__", None)
    main = Path(main).resolve() if main else None
    text = _script_text(lines)
    h = hashlib.sha256()
    h.update(text.encode("utf-8", "surrogateescape") + bytes(1))
    mods = []
    for m in list(sys.modules.values()):
        f = getattr(m, "__file__", None)
        if not f:
            continue
        p = Path(f).resolve()
        try:
            p.relative_to(TOOLS.resolve())
        except ValueError:
            continue
        if p.suffix == ".py" and p.name not in NOT_THE_MODEL:
            mods.append(p)
    # The checker itself, run as __main__, is in sys.modules too.
    named = _named_files(text)
    for p in sorted(set(mods)) + [ELF] + [Path(d) for d in data] + named:
        h.update(str(p.name).encode() + bytes(1))
        if p == main:
            h.update(_checker_text(p, cut))
        else:
            h.update(p.read_bytes() if p.exists() else b"missing")
        h.update(bytes(1))
    return h.hexdigest()[:40]


def model_cached(lines, run, data=(), cut=None):
    """run(lines)'s transcript, from the cache when nothing it depends on
    has changed. `data` names the files the model reads besides the ELF;
    `cut` is the line in the checker after which nothing is the model's."""
    if os.environ.get("NFSHP2_NO_MODEL_CACHE"):
        return run(lines)
    key = _model_key(lines, data, cut)
    path = MODEL_CACHE / (key + ".json")
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    got = run(lines)
    try:
        MODEL_CACHE.mkdir(parents=True, exist_ok=True)
        part = path.with_name("%s.%d.part" % (path.name, os.getpid()))
        part.write_text(json.dumps(got), encoding="utf-8")
        os.replace(part, path)
    except OSError:
        pass
    return got


# -------------------------------------------------------------- the run

def run_exe(argv, out_path, timeout):
    """The harness, its stdout into out_path: its exit code, HUNG when it
    is killed at `timeout` seconds."""
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(a) for a in argv], stdout=fh,
                               stderr=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        return HUNG
    return r.returncode


def _apply(text, before, after):
    crlf = "\r\n" in text
    probe = before.replace(NL, "\r\n") if crlf else before
    repl = after.replace(NL, "\r\n") if crlf else after
    n = text.count(probe)
    if n != 1:
        return None, "NOT FOUND" if n == 0 else "NOT UNIQUE"
    return text.replace(probe, repl, 1), None


def _judge(name, rc, got_path, base, diff, equivalent):
    if rc == HUNG:
        return "caught", "hung the harness (caught)"
    if rc != 0:
        return "caught", "crashed the harness (caught)"
    n = diff(base, Path(got_path).read_text(encoding="latin-1")
             .splitlines(), quiet=True)
    if n:
        return "caught", "caught, %d lines" % n
    if name in equivalent:
        return "equivalent", "survived, equivalent by construction"
    return "survived", "SURVIVED"


class Snapshot:
    """What a build of `sources` reads, copied out of the tree, and built
    once: each source's directory's headers (all of `3DS Files/source`'s,
    at any depth) and the sources themselves."""

    def __init__(self, sources, build_name, flags=None):
        self._tmp = tempfile.TemporaryDirectory(prefix="mutpar-")
        self.dir = Path(self._tmp.name)
        self.name = build_name
        self.flags = flags
        self.dirs = {}      # a directory of the tree -> its copy
        self.files = {}     # a file of the tree -> its copy
        self.sources = [_abs(x) for x in sources]
        for src in self.sources:
            dst = self._dir(src.parent) / src.name
            shutil.copyfile(src, dst)
            self.files[src] = dst
        self.inc = [self._dir(hostbuild.SRC.resolve())]
        objs = self.dir / "obj"
        objs.mkdir()
        self.objs = [objs / ("%03d-%s.o" % (i, x.stem))
                     for i, x in enumerate(self.sources)]
        base = self.dir / "base"
        base.mkdir()
        self.exe = hostbuild.build_objects(
            base, [(self.files[x], o)
                   for x, o in zip(self.sources, self.objs)],
            self.objs, build_name, flags, self.inc, quiet=True)

    def _dir(self, d):
        if d not in self.dirs:
            to = self.dir / ("d%d" % len(self.dirs))
            to.mkdir()
            deep = d == hostbuild.SRC.resolve()
            for f in (d.rglob("*") if deep else d.glob("*")):
                if f.suffix in hostbuild.HEADER_SUFFIXES and f.is_file():
                    dst = to / f.relative_to(d)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(f, dst)
                    self.files[f.resolve()] = dst
            self.dirs[d] = to
        return self.dirs[d]

    def text(self, rel):
        """The file's text as the snapshot has it, or None when the
        snapshot has no copy of it."""
        f = self.files.get(_abs(rel))
        return None if f is None else f.read_text(encoding="utf-8",
                                                  newline="")

    def build_source(self, tmp, rel, text):
        """The program with the source `rel` replaced by `text`."""
        orig = _abs(rel)
        src = Path(tmp) / orig.name
        with open(src, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        obj = Path(tmp) / "m.o"
        objs = list(self.objs)
        objs[self.sources.index(orig)] = obj
        own = self.dirs[orig.parent]
        inc = [own] + [d for d in self.inc if d != own]
        return hostbuild.build_objects(tmp, [(src, obj)], objs, self.name,
                                       self.flags, inc, quiet=True)

    def build_header(self, tmp, rel, text):
        """The program, every source compiled again from a copy of the
        snapshot in which the header `rel` is `text`."""
        tmp = Path(tmp)
        moved = {}
        for copy in self.dirs.values():
            moved[copy] = tmp / copy.name
            shutil.copytree(copy, moved[copy])
        hdr = self.files[_abs(rel)]
        for copy in self.dirs.values():
            if _inside(hdr, copy):
                hdr = moved[copy] / hdr.relative_to(copy)
                break
        with open(hdr, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        objs = [tmp / o.name for o in self.objs]
        todo = [(moved[self.dirs[x.parent]] / x.name, o)
                for x, o in zip(self.sources, objs)]
        return hostbuild.build_objects(tmp, todo, objs, self.name,
                                       self.flags,
                                       [moved[d] for d in self.inc],
                                       quiet=True)

    def cleanup(self):
        self._tmp.cleanup()


def _abs(rel):
    p = Path(rel)
    return (p if p.is_absolute() else ROOT / p).resolve()


def _inside(path, d):
    try:
        path.relative_to(d)
        return True
    except ValueError:
        return False


def run_pass(todo, sources, build_name, run, base, diff, equivalent,
             jobs=None, flags=None):
    """Each mutation (name, rel, before, after) of `todo` built from a
    snapshot of `sources` and run by run(exe, out_path) -> exit code, its
    transcript compared with `base` by diff(base, got, quiet=True).

    Prints one line per mutation, in order, and returns the tally:
    (caught, survived, missing, equivalent) with the last three lists of
    names. run must not print; mutpar.run_exe is one."""
    snap = Snapshot(sources, build_name, flags)
    try:
        out = snap.dir / "base" / "base.txt"
        rc = run(snap.exe, out)
        if rc != 0 or diff(base, out.read_text(encoding="latin-1")
                           .splitlines(), quiet=True):
            sys.exit("the snapshot's own build does not give the base "
                     "transcript (exit %d) -- did the tree change as the "
                     "pass began?" % rc)
        return _run_pass(snap, todo, sources, build_name, run, base, diff,
                         equivalent, jobs)
    finally:
        snap.cleanup()


def _run_pass(snap, todo, sources, build_name, run, base, diff, equivalent,
              jobs):
    caught, survived, missing, equal = 0, [], [], []
    srcs = set(snap.sources)

    def one(m):
        name, rel, before, after = m
        new, why = _apply(snap.text(rel), before, after)
        if new is None:
            return "missing", "PATTERN " + why
        with tempfile.TemporaryDirectory() as tmp:
            try:
                if _abs(rel) in srcs:
                    exe = snap.build_source(tmp, rel, new)
                else:
                    exe = snap.build_header(tmp, rel, new)
            except SystemExit:
                return "caught", "did not compile (caught)"
            out = Path(tmp) / "m.txt"
            rc = run(exe, out)
            return _judge(name, rc, out, base, diff, equivalent)

    def in_place(m):
        name, rel, before, after = m
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        new, why = _apply(text, before, after)
        if new is None:
            return "missing", "PATTERN " + why
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = hostbuild.build(tmp, sources, name=build_name,
                                          quiet=True)
                except SystemExit:
                    return "caught", "did not compile (caught)"
                out = Path(tmp) / "m.txt"
                rc = run(exe, out)
                return _judge(name, rc, out, base, diff, equivalent)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))

    def tally(m, result):
        nonlocal caught
        kind, line = result
        print("  %-44s %s" % (m[0], line), flush=True)
        if kind == "caught":
            caught += 1
        elif kind == "survived":
            survived.append(m[0])
        elif kind == "missing":
            missing.append(m[0])
        else:
            equal.append(m[0])

    out_of_tree = [m for m in todo if snap.text(m[1]) is not None]
    rest = [m for m in todo if m not in out_of_tree]
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=jobs or JOBS) as pool:
        for m, result in zip(out_of_tree, pool.map(one, out_of_tree)):
            tally(m, result)
    for m in rest:
        tally(m, in_place(m))
    return caught, survived, missing, equal


def timeout_for(seconds):
    """A mutant's time limit from the base harness's own run: generous,
    as JOBS of them share the machine, but far short of a minute for a
    harness that takes two seconds."""
    return max(15.0, 10.0 * seconds)


def summarize(todo, only, equivalent_names, tally):
    """The pass's last lines, from run_pass's tally: the exit code, 1 when
    a mutant survived unexplained, a pattern was not found, or a name in
    the list of equivalents was caught or names no mutation."""
    caught, survived, missing, equivalent = tally
    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in equivalent_names]
    ran = {m[0] for m in todo}
    stale = [n for n in equivalent_names
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
