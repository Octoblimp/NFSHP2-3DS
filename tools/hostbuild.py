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
"""
import io
import os
import shutil
import subprocess
import sys
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


def build(tmp, sources, name="hosttest", flags=None):
    """Compile `sources` into `tmp`, returning the executable's path."""
    recover()
    flags = list(flags or FLAGS)
    srcs = [Path(s) if Path(s).is_absolute() else (ROOT / s) for s in sources]
    for s in srcs:
        if not s.exists():
            sys.exit("no such source: %s" % s)
    exe = Path(tmp) / (name + (".exe" if os.name == "nt" else ""))
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
        sys.stderr.write(r.stdout + r.stderr)
        sys.exit("compile failed (msys2 bash)")

    if not cc:
        sys.exit("no host C compiler found (set CC)")
    sys.stderr.write(direct_err)
    sys.exit("compile failed")
