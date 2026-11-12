#!/usr/bin/env python3
r"""NFSHP2-3DS Packer: makes the SD card's NFSHP2 folder from your own PS2
disc of Need for Speed: Hot Pursuit 2, in one go.

It runs the README's steps 2 to 4 (zdir_extract.py --retail --decompress,
audio_pack.py, make_card.py) and reads the disc's files from wherever they
are: a disc image (.iso), the disc itself in a drive, or a folder holding
ZDIR.BIN and ZZDATA.BIN. An image is read in place, so ZZDATA.BIN (3 GB)
never has to be copied out of it first.

The window is hp2_packer_gui.pyw; this is the same work from a command
line, and the core both share:

    python tools/hp2_packer.py --disc "NFSHP2.iso" --card E:\
    python tools/hp2_packer.py --disc D:\ --card sd-card --keep-work
    python tools/hp2_packer.py --disc "PS2 Files/Full Game" --card E:\ --prune

--work is the folder the disc is extracted into (3.3 GB while it runs;
extracted-retail/ beside tools/ by default, which is where the README's
steps put it). If this program made it, it is deleted at the end unless
--keep-work is given; a folder it didn't make is kept. Files already
extracted and unchanged aren't written again, and the card's copy skips
files of the same size and time, so a run that was stopped can simply be
started again.
--prune also deletes files in the card's NFSHP2 folder that aren't the
disc's (the game would load a leftover one); NFSHP2/SAVES is never
touched.

Standard library only, Python 3.8 or newer.
"""
import argparse
import calendar
import datetime
import os
import shutil
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import audio_pack  # noqa: E402
import make_card  # noqa: E402
import zdir_extract  # noqa: E402

APP_NAME = "NFSHP2-3DS Packer"
# The disc the port was made from and tested with.
TESTED_SERIAL = "SLES_507.31"
SECTOR = 2048
# Space the work folder needs while it runs: the extraction is 3.3 GB.
WORK_NEED = int(3.5e9)
CARD_NEED = int(3.0e9)
# Left in a work folder this program made, so it knows to delete it.
MARKER = "made-by-nfshp2-packer.txt"
# The disc's files are dated with the disc's own date, so a card made
# before has them at the same size and time and they aren't copied again.
# Raise this when the packer starts writing different bytes for the same
# disc: each step moves every date 10 seconds, so every card gets the new
# files.
OUTPUT_REVISION = 0


class Cancelled(Exception):
    """The user stopped the run."""


def app_dir():
    """The folder the program is in: the exe's when frozen, else tools/."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return HERE


def names_file():
    """docs/zdir_names_retail.txt: the disc's file names by hash."""
    cands = []
    if hasattr(sys, "_MEIPASS"):
        cands.append(Path(sys._MEIPASS) / "zdir_names_retail.txt")
    cands += [HERE / "zdir_names_retail.txt",
              HERE.parent / "docs" / "zdir_names_retail.txt"]
    for c in cands:
        if c.is_file():
            return c
    raise SystemExit("zdir_names_retail.txt is missing: it should be beside "
                     "this program or in docs/")


def default_work():
    """Where the disc is extracted. In the repository that is
    extracted-retail/, where the README's own steps put it."""
    if not getattr(sys, "frozen", False) and (HERE.parent / "docs").is_dir():
        return HERE.parent / "extracted-retail"
    return app_dir() / "extracted-retail"


# ------------------------------------------------------------------ the disc

class Disc:
    """ZDIR.BIN and ZZDATA.BIN, from a disc image or a folder.

    zdir is ZDIR.BIN's bytes; zzdata, zz_base and zz_size say where
    ZZDATA.BIN's bytes are; serial is the boot file SYSTEM.CNF names, or
    None; time is ZZDATA.BIN's date (the image's own record of it, else
    the file's time), which the same disc gives every run."""

    def __init__(self, path):
        p = Path(path)
        self.path = p
        self.serial = None
        if p.is_file():
            self._open_image(p)
        elif p.is_dir():
            self._open_folder(p)
        else:
            raise SystemExit("%s isn't a file or a folder" % p)

    def _open_folder(self, p):
        found = {}
        for child in p.iterdir():
            found[child.name.upper()] = child
        if "ZDIR.BIN" not in found or "ZZDATA.BIN" not in found:
            raise SystemExit(
                "%s has no ZDIR.BIN and ZZDATA.BIN. Choose the disc's drive, "
                "a disc image (.iso), or the folder you copied those two "
                "files into." % p)
        self.zdir = found["ZDIR.BIN"].read_bytes()
        self.zzdata = str(found["ZZDATA.BIN"])
        self.zz_base = 0
        self.zz_size = found["ZZDATA.BIN"].stat().st_size
        self.time = found["ZZDATA.BIN"].stat().st_mtime
        if "SYSTEM.CNF" in found:
            self.serial = boot_serial(found["SYSTEM.CNF"].read_bytes())

    def _open_image(self, p):
        files = iso_root_files(p)
        if "ZDIR.BIN" not in files or "ZZDATA.BIN" not in files:
            raise SystemExit(
                "%s has no ZDIR.BIN and ZZDATA.BIN in its root: is it the "
                "Hot Pursuit 2 disc?" % p.name)
        with open(p, "rb") as f:
            lba, size, _ = files["ZDIR.BIN"]
            f.seek(lba * SECTOR)
            self.zdir = f.read(size)
            if "SYSTEM.CNF" in files:
                lba, size, _ = files["SYSTEM.CNF"]
                f.seek(lba * SECTOR)
                self.serial = boot_serial(f.read(min(size, 4096)))
        lba, size, when = files["ZZDATA.BIN"]
        self.zzdata = str(p)
        self.zz_base = lba * SECTOR
        self.zz_size = size
        self.time = when or p.stat().st_mtime
        if self.zz_base + size > p.stat().st_size:
            raise SystemExit("%s is cut short: ZZDATA.BIN runs past its end. "
                             "Make the image again." % p.name)


def iso_root_files(path):
    """{NAME: (first sector, size)} for the files in an ISO 9660 image's
    root. A PS2 DVD image is one, with 2048-byte sectors."""
    with open(path, "rb") as f:
        f.seek(16 * SECTOR)
        pvd = f.read(SECTOR)
        if pvd[0:1] != b"\x01" or pvd[1:6] != b"CD001":
            raise SystemExit(
                "%s isn't an ISO disc image (no ISO 9660 header). Make a "
                ".iso of the disc, or choose the disc's drive." % Path(path).name)
        block = struct.unpack_from("<H", pvd, 128)[0]
        if block != SECTOR:
            raise SystemExit("%s has %d-byte blocks; only 2048 is supported"
                             % (Path(path).name, block))
        root = pvd[156:156 + 34]
        lba, size = struct.unpack_from("<I", root, 2)[0], \
            struct.unpack_from("<I", root, 10)[0]
        f.seek(lba * SECTOR)
        data = f.read(size)
    files = {}
    i = 0
    while i < len(data):
        n = data[i]
        if n == 0:
            # Records don't cross sectors: the rest of this one is padding.
            i = (i // SECTOR + 1) * SECTOR
            continue
        rec = data[i:i + n]
        flags = rec[25]
        name_len = rec[32]
        name = rec[33:33 + name_len].decode("latin-1", "replace")
        if not flags & 2 and name not in ("\x00", "\x01"):
            name = name.split(";")[0].upper()
            files[name] = (struct.unpack_from("<I", rec, 2)[0],
                           struct.unpack_from("<I", rec, 10)[0],
                           record_time(rec[18:25]))
        i += n
    return files


def record_time(d):
    """A directory record's date (years since 1900, month, day, hour,
    minute, second, offset from GMT in quarter hours) as a Unix time, or
    None when it isn't one."""
    try:
        t = calendar.timegm((1900 + d[0], d[1], d[2], d[3], d[4], d[5]))
        dt = datetime.datetime(1900 + d[0], d[1], d[2], d[3], d[4], d[5])
    except (ValueError, OverflowError):
        return None
    off = d[6] - 256 if d[6] > 127 else d[6]
    return t - off * 15 * 60 if dt.year >= 1980 else None


def boot_serial(cnf):
    """SLES_507.31 out of SYSTEM.CNF's BOOT2 line, or None."""
    for line in cnf.decode("latin-1", "replace").splitlines():
        if line.strip().upper().startswith("BOOT2"):
            v = line.split("=", 1)[-1].strip()
            v = v.replace("/", "\\").split("\\")[-1]
            return v.split(";")[0].upper() or None
    return None


# ------------------------------------------------------------------ the card

def card_root(path):
    """The folder the NFSHP2 folder goes in. Choosing the NFSHP2 folder
    itself means its parent, not NFSHP2/NFSHP2."""
    p = Path(path)
    if p.name.upper() == "NFSHP2":
        return p.parent
    return p


def free_bytes(path):
    p = Path(path)
    while not p.exists() and p.parent != p:
        p = p.parent
    return shutil.disk_usage(p).free


def safe_to_delete(work):
    """Only a folder this program's extraction made: its manifest is there
    and nothing in it is outside what an extraction writes."""
    w = Path(work)
    if not (w / "manifest.csv").is_file():
        return False
    known = {"MANIFEST.CSV", "CARS", "FRONTEND", "GLOBAL", "LANGUAGES",
             "MOVIES", "NIS", "REPLAY", "SOUND", "TRACKS", "MARKERS",
             "UNKNOWN", "KEY.TXT", "NFS6.ICO", "PAL.TAG", MARKER.upper()}
    return all(c.name.upper() in known for c in w.iterdir())


# ------------------------------------------------------------------- the run

STEPS = ("Reading the disc", "Extracting the disc's files",
         "Building the 3DS sound banks", "Copying to the SD card",
         "Cleaning up")


def run(disc, card, work=None, prune=False, keep_work=False,
        log=print, step=None, progress=None, cancel=None):
    """Do the whole conversion. step(index, title) is called as each of
    STEPS starts, progress(done, total) within it, and cancel() -> True
    stops the run at the next file with Cancelled."""
    work = Path(work) if work else default_work()
    card = card_root(card)
    t0 = time.monotonic()

    def go(i):
        if step:
            step(i, STEPS[i])
        log("== %s" % STEPS[i])

    def tick(done, total):
        if cancel and cancel():
            raise Cancelled()
        if progress:
            progress(done, total)

    go(0)
    d = Disc(disc)
    log("Disc: %s" % d.path)
    if d.serial:
        log("Serial: %s" % d.serial)
        if d.serial != TESTED_SERIAL:
            log("Note: the port was made from %s (the PAL disc). Other "
                "releases are untested." % TESTED_SERIAL)
    if len(d.zdir) == 0 or len(d.zdir) % 12:
        raise SystemExit("ZDIR.BIN is %d bytes, which isn't a directory of "
                         "this game" % len(d.zdir))
    tick(1, 1)

    have_extract = (work / "manifest.csv").is_file()
    if not have_extract and free_bytes(work) < WORK_NEED:
        raise SystemExit("The work folder %s needs about %.1f GB free and has "
                         "%.1f GB" % (work, WORK_NEED / 1e9,
                                      free_bytes(work) / 1e9))
    card.mkdir(parents=True, exist_ok=True)
    if not (card / "NFSHP2").is_dir() and free_bytes(card) < CARD_NEED:
        raise SystemExit("%s needs about %.1f GB free and has %.1f GB"
                         % (card, CARD_NEED / 1e9, free_bytes(card) / 1e9))

    # Only a work folder this program made is deleted at the end: one it
    # makes is marked, so a run that was stopped and started again still
    # cleans up after itself.
    if not work.exists():
        work.mkdir(parents=True)
        (work / MARKER).write_text(APP_NAME + " made this folder.\n")
    made_here = (work / MARKER).is_file()

    go(1)
    zdir_extract.extract(d.zdir, d.zzdata, work, names_file(),
                         decompress=True, zz_base=d.zz_base,
                         zz_size=d.zz_size, log=log, warn=log, progress=tick)

    go(2)
    audio_pack.pack(work / "SOUND", work / "SOUND", log=log, progress=tick)

    when = d.time + 10 * OUTPUT_REVISION
    for p in work.rglob("*"):
        # The sound banks are audio_pack.py's, not the disc's: they keep
        # their own time (and make_card wants them newer than the .MSH).
        if (p.is_file() and p.suffix.upper() != ".SBK"
                and p.name != MARKER and p.stat().st_mtime != when):
            os.utime(p, (when, when))

    go(3)
    extra = make_card.make(card, work, prune=prune, log=log, progress=tick)

    go(4)
    if keep_work:
        log("Kept the extracted files in %s" % work)
    elif not made_here:
        log("Kept %s: this program didn't make it" % work)
    elif safe_to_delete(work):
        shutil.rmtree(work)
        log("Deleted the work folder %s" % work)
    else:
        log("Left %s alone: it holds files the extraction didn't make"
            % work)
    tick(1, 1)
    mins = (time.monotonic() - t0) / 60.0
    log("Done in %.1f minutes. %s is ready: put the card in the 3DS and "
        "start the game." % (mins, card / "NFSHP2"))
    return extra


def main():
    ap = argparse.ArgumentParser(
        description="Make the SD card's NFSHP2 folder from your PS2 disc of "
                    "Need for Speed: Hot Pursuit 2.")
    ap.add_argument("--disc", required=True,
                    help="a disc image (.iso), the disc's drive, or a folder "
                         "with ZDIR.BIN and ZZDATA.BIN")
    ap.add_argument("--card", required=True,
                    help="the SD card's root (E:\\), or a folder to copy to "
                         "the card's root later")
    ap.add_argument("--work", default=None,
                    help="where to extract the disc (3.3 GB while it runs; "
                         "default %s)" % default_work())
    ap.add_argument("--keep-work", action="store_true",
                    help="keep the extracted files afterwards")
    ap.add_argument("--prune", action="store_true",
                    help="delete files in the card's NFSHP2 folder that "
                         "aren't the disc's (NFSHP2/SAVES is kept)")
    a = ap.parse_args()
    try:
        run(a.disc, a.card, a.work, a.prune, a.keep_work)
    except Cancelled:
        sys.exit("stopped")
    except KeyboardInterrupt:
        sys.exit("stopped")


if __name__ == "__main__":
    main()
