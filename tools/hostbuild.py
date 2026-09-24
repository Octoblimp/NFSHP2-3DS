#!/usr/bin/env python3
r"""Build a `3DS Files/source` module for the host, so it can be tested.

The modules under `3DS Files/source` that only parse data -- bchunk, texpack,
bfont, langtab -- are deliberately free of <3ds.h>, so the same code that will
run on the handheld can be compiled here and checked against the Python tools
that cracked the formats. This is the compile half of that; the harnesses live
in tools/src/ and the checkers next to this file.

On this machine the only host compiler is the one inside devkitPro's msys2,
and it finds its own /usr/include only when it runs in that environment --
invoked from Git Bash it cannot even locate stdio.h. So: try `cc` directly,
then retry through the msys2 login shell, which is what tools/build_cia.ps1
does for `make` and for the same underlying reason.

Every source is compiled on its own into an object cached by its content --
see "the object cache" below -- so a mutation pass rebuilds the one file it
changed rather than the whole harness.
"""
import concurrent.futures
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "3DS Files" / "source"
BS = chr(92)
NL = chr(10)

MSYS_BASH = Path("C:/devkitPro/msys2/usr/bin/bash.exe")
# -ffp-contract=off so the host cannot fuse a multiply and an add into
# one rounding step. The PS2 does not fuse, and a checker that let the
# host do it would report a diff that only exists on this machine.
FLAGS = ["-O2", "-std=c11", "-Wall", "-Wextra", "-ffp-contract=off"]


def msys(path):
    """A Windows path as msys2 spells it: C:@foo -> /c/foo (@ = backslash)."""
    p = str(path).replace(BS, "/")
    if len(p) > 1 and p[1] == ":":
        p = "/" + p[0].lower() + p[2:]
    return p


def quote(path):
    return "'" + msys(path).replace("'", "'" + BS + "''") + "'"


# ------------------------------------------------------------------ mutants
#
# Every *_check.py --mutate writes a mutant into a ported source and puts the
# original back in a `finally`. A process that is killed -- TaskStop, a closed
# terminal -- never reaches the `finally`, and the source keeps the mutant.
# That happened once: drivetarget.c kept `sr-count-signed` through a whole
# session. The mutant was an equivalent one, so every plain run stayed clean,
# and only the next --mutate run's PATTERN NOT FOUND gave it away.
#
# So the first write a process makes to a file parks the file's original
# beside it as `<name>.<pid>.mutate-backup` (gitignored), and the write that
# puts the original back removes it. build(), which every checker calls
# before it runs anything, restores each backup whose process has gone.
#
# Windows returns EINVAL for a write to a file the OneDrive client has open
# behind us, and a retry gets through -- hence WRITE_TRIES.

BACKUP_SUFFIX = ".mutate-backup"
BACKUP_DIRS = (SRC, ROOT / "tools" / "src")
WRITE_TRIES = 5


def _write(path, text):
    for attempt in range(WRITE_TRIES):
        try:
            # newline="" both ways, always: the tree mixes CRLF and LF, and a
            # translating write turns a CRLF original into CR CR LF on
            # restore. camera_check and trackroute_check did exactly that to
            # three sources, one extra CR per line per pass.
            path.write_text(text, encoding="utf-8", newline="")
            return
        except OSError:
            if attempt == WRITE_TRIES - 1:
                raise
            time.sleep(0.2 * (attempt + 1))


def _alive(pid):
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    # Not os.kill: on Windows signal 0 is CTRL_C_EVENT.
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = ctypes.c_void_p
    k.GetExitCodeProcess.argtypes = [ctypes.c_void_p,
                                     ctypes.POINTER(ctypes.c_ulong)]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: it exists
    try:
        code = ctypes.c_ulong()
        if not k.GetExitCodeProcess(h, ctypes.byref(code)):
            return True
        return code.value == 259                # STILL_ACTIVE
    finally:
        k.CloseHandle(h)


def _backup_path(path, pid):
    return path.with_name("%s.%d%s" % (path.name, pid, BACKUP_SUFFIX))


def _backups():
    """(backup, source, pid) for every parked original."""
    for d in BACKUP_DIRS:
        for b in d.rglob("*" + BACKUP_SUFFIX):
            base, _, pid = b.name[:-len(BACKUP_SUFFIX)].rpartition(".")
            # bslotpool_mutate/geometry_mutate park `<name>.mutate-backup`,
            # with no pid, and recover it themselves.
            if base and pid.isdigit():
                yield b, b.with_name(base), int(pid)


def recover():
    """Put back every original whose mutating process is gone."""
    me = os.getpid()
    for b, src, pid in list(_backups()):
        if pid == me:
            continue
        if _alive(pid):
            sys.stderr.write("warning: pid %d has a mutant of %s in flight; "
                             "anything built from it now sees the mutant%s"
                             % (pid, src.name, NL))
            continue
        _write(src, b.read_text(encoding="utf-8", newline=""))
        b.unlink()
        sys.stderr.write("restored %s: pid %d wrote a mutant into it and "
                         "died before putting the original back%s"
                         % (src.name, pid, NL))


def write_source(path, text):
    """Write a mutant, or put an original back. The checkers' own
    write_source() is this."""
    path = Path(path).resolve()
    mine = _backup_path(path, os.getpid())
    if not mine.exists():
        for b, src, pid in list(_backups()):
            if src.resolve() == path and pid != os.getpid():
                if _alive(pid):
                    sys.exit("pid %d is mutating %s already -- two passes "
                             "over one file would restore each other's "
                             "mutants" % (pid, path.name))
                recover()
        _write(mine, path.read_text(encoding="utf-8", newline=""))
    _write(path, text)
    if text == mine.read_text(encoding="utf-8", newline=""):
        mine.unlink()


# ------------------------------------------------------------ the object cache
#
# A mutation pass builds its harness once per mutant, and every mutant
# changes one file of the twenty-odd the harness links; compiling them all
# at -O2 each time was most of the pass. So each source is compiled alone,
# with -c, and the object is kept under a key that covers everything the
# compile reads that can change: the flags, the source's path and bytes,
# and every header and .inc in `3DS Files/source` and beside each source.
# System headers are taken as fixed. Changing any one header recompiles
# everything, which is the safe way round. Nothing is cross-module at -O2
# without LTO, so the objects link to the same program the single
# `gcc a.c b.c ...` did.
#
# Sources inside `tmp` -- generated harnesses -- are compiled every time
# and never kept. The misses compile in parallel. The cache lives in the
# system temp directory, not the tree, which OneDrive syncs; entries
# nothing has used for a week are dropped. HOSTBUILD_NO_CACHE=1 builds the
# old way, in one gcc invocation.

CACHE = Path(os.environ.get("HOSTBUILD_CACHE")
             or Path(tempfile.gettempdir()) / "nfshp2-hostbuild")
HEADER_SUFFIXES = (".h", ".inc")
CACHE_DAYS = 7
_pruned = False
# "direct" or "msys", once a build that compiled something has told them
# apart. A build whose objects all come from the cache only links, and the
# link works outside msys2 where a compile cannot find <stddef.h>, so it
# decides nothing. It once did: a --mutate pass whose first build was all
# hits went direct, and every mutant after it failed to compile and was
# counted as caught.
_mode = None


def _headers_digest(dirs):
    h = hashlib.sha256()
    for d in sorted(set(Path(x).resolve() for x in dirs)):
        files = d.rglob("*") if d == SRC.resolve() else d.glob("*")
        for f in sorted(files):
            if f.suffix in HEADER_SUFFIXES and f.is_file():
                h.update(str(f.relative_to(d)).encode() + bytes(1))
                h.update(f.read_bytes() + bytes(1))
    return h.hexdigest()


def _key(src, flags, headers):
    h = hashlib.sha256()
    for part in (chr(1).join(flags), str(src.resolve()), headers):
        h.update(part.encode() + bytes(1))
    h.update(src.read_bytes())
    return h.hexdigest()[:40]


def _inside(path, d):
    try:
        path.resolve().relative_to(Path(d).resolve())
        return True
    except ValueError:
        return False


def _prune():
    global _pruned
    if _pruned:
        return
    _pruned = True
    cutoff = time.time() - CACHE_DAYS * 86400
    for f in CACHE.glob("*"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass


def _keep(obj, cached):
    """Move a fresh object into the cache without a reader ever seeing half
    of it: copy under a private name, then rename over."""
    part = cached.with_name("%s.%d.part" % (cached.name, os.getpid()))
    try:
        shutil.copyfile(obj, part)
        os.replace(part, cached)
    except OSError:
        try:
            part.unlink()
        except OSError:
            pass


class BuildEnvironmentError(RuntimeError):
    """The toolchain failed and said nothing about the code: a locked
    object on OneDrive, a shell that did not start. A mutation pass counts
    a failed compile as a catch, so this is raised rather than exited --
    it is not caught there, and the pass stops instead of scoring a broken
    environment. One pass once reported nineteen mutants in a row as "did
    not compile" with no diagnostic; rerun, all nineteen were caught on
    the transcript."""


def _fail(err, what):
    sys.stderr.write(err)
    if "error" not in err.lower():
        raise BuildEnvironmentError("%s with no diagnostic -- the build "
                                    "environment, not the code" % what)
    sys.exit(what)


def _compile_direct(cc, flags, todo, exe, objs):
    env = dict(os.environ)
    env.setdefault("TMPDIR", "/tmp")

    def one(job):
        src, obj = job
        return subprocess.run([cc] + flags + ["-I", str(SRC), "-c", str(src),
                               "-o", str(obj)],
                              capture_output=True, text=True, env=env)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        rs = list(pool.map(one, todo))
    err = "".join(r.stdout + r.stderr for r in rs)
    if any(r.returncode for r in rs):
        return False, err
    r = subprocess.run([cc] + flags + ["-o", str(exe)] + [str(o) for o in objs],
                       capture_output=True, text=True, env=env)
    return r.returncode == 0, err + r.stdout + r.stderr


def _compile_msys(tmp, flags, todo, exe, objs):
    fl = " ".join(flags)
    lines = ["fail=0"]
    for i, (src, obj) in enumerate(todo):
        lines.append("gcc %s -I %s -c %s -o %s 2>%s & p%d=$!"
                     % (fl, quote(SRC), quote(src), quote(obj),
                        quote(str(obj) + ".err"), i))
    for i in range(len(todo)):
        lines.append("wait $p%d || fail=1" % i)
    for src, obj in todo:
        lines.append("cat %s >&2" % quote(str(obj) + ".err"))
    lines.append("[ $fail = 0 ] || exit 1")
    lines.append("gcc %s -o %s %s" % (fl, quote(exe),
                                      " ".join(quote(o) for o in objs)))
    script = Path(tmp) / "build.sh"
    with io.open(script, "w", encoding="utf-8", newline=NL) as fh:
        fh.write(NL.join(lines) + NL)
    r = subprocess.run([str(MSYS_BASH), "-l", msys(script)],
                       capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


def _build_cached(tmp, srcs, exe, flags):
    global _mode
    tmp = Path(tmp)
    CACHE.mkdir(parents=True, exist_ok=True)
    _prune()
    headers = _headers_digest([SRC] + [s.parent for s in srcs])
    plan = []
    for i, s in enumerate(srcs):
        cached = (None if _inside(s, tmp)
                  else CACHE / (_key(s, flags, headers) + ".o"))
        fresh = tmp / ("%03d-%s.o" % (i, s.stem))
        hit = cached is not None and cached.exists()
        plan.append((s, cached, fresh, hit))
    todo = [(s, fresh) for s, cached, fresh, hit in plan if not hit]
    objs = [cached if hit else fresh for s, cached, fresh, hit in plan]
    for s, cached, fresh, hit in plan:
        if hit:
            try:
                os.utime(cached)
            except OSError:
                pass

    cc = (os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")
          or shutil.which("clang"))
    ok, err, direct_err = False, "", ""
    if cc and _mode != "msys":
        ok, err = _compile_direct(cc, flags, todo, exe, objs)
        if ok and todo:
            _mode = "direct"
        elif not ok:
            direct_err = err
    if not ok and _mode != "direct" and MSYS_BASH.exists():
        ok, err = _compile_msys(tmp, flags, todo, exe, objs)
        if ok and todo:
            _mode = "msys"
        else:
            _fail(err, "compile failed (msys2 bash)")
    if not ok:
        if not cc:
            sys.exit("no host C compiler found (set CC)")
        _fail(direct_err or err, "compile failed")
    if err.strip():
        print("compiler warnings:" + NL + err.rstrip())
    for s, cached, fresh, hit in plan:
        if cached is not None and not hit:
            _keep(fresh, cached)
    return exe


def build(tmp, sources, name="hosttest", flags=None):
    """Compile `sources` into `tmp`, returning the executable's path."""
    recover()
    flags = list(flags or FLAGS)
    srcs = [Path(s) if Path(s).is_absolute() else (ROOT / s) for s in sources]
    for s in srcs:
        if not s.exists():
            sys.exit("no such source: %s" % s)
    exe = Path(tmp) / (name + (".exe" if os.name == "nt" else ""))
    if not os.environ.get("HOSTBUILD_NO_CACHE"):
        return _build_cached(tmp, srcs, exe, flags)
    direct_err = ""

    cc = (os.environ.get("CC") or shutil.which("cc") or shutil.which("gcc")
          or shutil.which("clang"))
    if cc:
        cmd = ([cc] + flags + ["-I", str(SRC), "-o", str(exe)]
               + [str(x) for x in srcs])
        # devkitPro's msys2 gcc takes its TMPDIR from the Windows environment
        # and then resolves it against the msys root, where it does not exist,
        # so cc1 cannot write its .s.
        env = dict(os.environ)
        env.setdefault("TMPDIR", "/tmp")
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if r.returncode == 0:
            if r.stderr.strip():
                print("compiler warnings:" + NL + r.stderr.rstrip())
            return exe
        direct_err = r.stdout + r.stderr

    if MSYS_BASH.exists():
        script = Path(tmp) / "build.sh"
        body = ("set -e" + NL + "gcc %s -I %s -o %s %s" + NL) % (
            " ".join(flags), quote(SRC), quote(exe),
            " ".join(quote(x) for x in srcs))
        with io.open(script, "w", encoding="utf-8", newline=NL) as fh:
            fh.write(body)
        r = subprocess.run([str(MSYS_BASH), "-l", msys(script)],
                           capture_output=True, text=True)
        if r.returncode == 0:
            if r.stderr.strip():
                print("compiler warnings:" + NL + r.stderr.rstrip())
            return exe
        _fail(r.stdout + r.stderr, "compile failed (msys2 bash)")

    if not cc:
        sys.exit("no host C compiler found (set CC)")
    _fail(direct_err, "compile failed")
