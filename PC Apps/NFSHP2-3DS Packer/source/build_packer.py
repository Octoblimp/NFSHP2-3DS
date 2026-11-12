#!/usr/bin/env python3
"""Builds NFSHP2-3DS Packer into a folder that needs no Python, with
PyInstaller (pip install pyinstaller):

    python tools/build_packer.py [--out "<folder>"]

The folder (default: <repo>/PC Apps/NFSHP2-3DS Packer):

    NFSHP2-3DS Packer(.exe)   the window
    nfshp2-packer(.exe)       the same from a command line
                              (nfshp2-packer --help)
    README.txt
    source/                   what both are built from: the packer's .py
                              files, the disc's name list, the icon and
                              this script, which runs from there and
                              rebuilds the folder as it is

Each program is one file (PyInstaller --onefile), so either can be copied
anywhere on its own. Without them the same runs from Python 3.8 or newer:
`python source/hp2_packer_gui.pyw`, or the README's steps one by one.

The build then opens both programs back up and checks that nothing in
them names the folder they were built in or this computer's user, since
PyInstaller would otherwise keep the absolute path of every file it
compiled.
"""
import argparse
import getpass
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
# Run from a built folder's source/: rebuild beside that folder.
IN_APP = (TOOLS.name == "source"
          and (TOOLS / "zdir_names_retail.txt").is_file())
ROOT = TOOLS.parent
DEFAULT_OUT = (ROOT.parent / (ROOT.name + " (rebuilt)") if IN_APP
               else ROOT / "PC Apps" / "NFSHP2-3DS Packer")
GUI_NAME = "NFSHP2-3DS Packer"
CLI_NAME = "nfshp2-packer"
SOURCES = ["hp2_packer.py", "hp2_packer_gui.pyw", "zdir_extract.py",
           "audio_pack.py", "audio_convert.py", "make_card.py", "bhash.py",
           "lzdecompress.py", "build_packer.py"]

README = """NFSHP2-3DS Packer
=================

Makes the NFSHP2 folder that the 3DS port of Need for Speed: Hot Pursuit 2
reads, from your own PS2 disc of the game. Nothing needs installing.

  NFSHP2-3DS Packer   Choose the disc and your SD card, and press
                      "Make SD card files". The disc can be a disc image
                      (.iso), the disc itself in a drive, or a folder with
                      the disc's ZDIR.BIN and ZZDATA.BIN. It takes a few
                      minutes, most of them copying 2.9 GB to the card.

It needs about 3.3 GB free for the disc's unpacked files while it runs
(deleted at the end unless you keep them) and 2.9 GB on the SD card. Saves
in NFSHP2/SAVES are never touched. Then install NFSHP2-3DS.cia with FBI and
start the game. The port was made from SLES-50731, the PAL disc; others
are untested.

Command line (the same work without a window):

  nfshp2-packer --disc "<disc image or drive>" --card E:\\
  nfshp2-packer --disc D:\\ --card "<folder>" --keep-work --prune
  nfshp2-packer --help     every option

source/ holds the Python both programs are built from. With Python 3.8 or
newer installed, the same runs without the .exe files:

  python source/hp2_packer_gui.pyw
  python source/hp2_packer.py --disc ... --card ...

and `python source/build_packer.py` (with PyInstaller) builds this folder
again. In the NFSHP2-3DS repository they are in tools/, and the README's
Installing section has the step-by-step Python commands as well.
"""


def make_icon(dest):
    """An original icon: a road at night under a light bar. Needs Pillow;
    without it the programs get Python's own."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Pillow isn't installed: building without an icon")
        return None, None
    n = 256
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, n - 8, n - 8), 40, fill=(18, 22, 34, 255))
    # The light bar: red and blue.
    d.rounded_rectangle((44, 46, 126, 82), 12, fill=(214, 40, 48, 255))
    d.rounded_rectangle((130, 46, 212, 82), 12, fill=(40, 98, 220, 255))
    # The road, narrowing to the horizon, and its centre line.
    d.polygon([(40, 236), (216, 236), (146, 110), (110, 110)],
              fill=(70, 74, 86, 255))
    for y0, y1, w in ((122, 140, 3), (156, 180, 5), (198, 230, 8)):
        d.rectangle((128 - w, y0, 128 + w, y1), fill=(240, 200, 60, 255))
    png = dest / "icon.png"
    ico = dest / "icon.ico"
    im.save(png)
    im.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                        (128, 128), (256, 256)])
    return png, ico


def names_list():
    for c in (TOOLS / "zdir_names_retail.txt",
              ROOT / "docs" / "zdir_names_retail.txt"):
        if c.is_file():
            return c
    sys.exit("zdir_names_retail.txt not found (docs/ or beside this script)")


def pyinstaller(stage, script, name, windowed, icon, data):
    sep = ";" if os.name == "nt" else ":"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "--onefile", "--name", name,
           "--distpath", str(stage / "dist"),
           "--workpath", str(stage / "build"),
           "--specpath", str(stage),
           "--paths", str(stage / "src"),
           "--exclude-module", "numpy", "--exclude-module", "PIL"]
    cmd.append("--windowed" if windowed else "--console")
    if not windowed:
        cmd += ["--exclude-module", "tkinter"]
    if icon:
        cmd += ["--icon", str(icon)]
    for src in data:
        cmd += ["--add-data", "%s%s." % (src, sep)]
    cmd.append(str(stage / "src" / script))
    print("PyInstaller: %s" % name)
    subprocess.run(cmd, check=True, cwd=str(stage))
    exe = stage / "dist" / (name + (".exe" if os.name == "nt" else ""))
    if not exe.is_file():
        sys.exit("PyInstaller made no %s" % exe.name)
    return exe


# ------------------------------------------------- what the programs hold

def code_strings(co, out):
    out.append(co.co_filename)
    for c in co.co_consts:
        if hasattr(c, "co_filename"):
            code_strings(c, out)
        elif isinstance(c, str):
            out.append(c)


def private_words():
    """The build folder and user name, in the forms a file might hold."""
    # As paths only: a bare name can be anyone's (Python's own files name
    # their authors).
    user = getpass.getuser()
    words = {os.path.expanduser("~"), str(TOOLS), str(ROOT),
             "\\Users\\" + user, "/Users/" + user, "/home/" + user}
    words = {w for w in words if w and len(w) >= 3}
    return words


def scan(exe):
    """Every place in the program that names a private word."""
    from PyInstaller.archive.readers import CArchiveReader
    words = private_words()
    needles = []
    for w in words:
        for v in {w, w.lower(), w.replace("\\", "/")}:
            needles += [v.encode("utf-8"), v.encode("utf-16-le")]
    hits = []

    def look(where, blob):
        low = blob.lower()
        for nd in needles:
            if nd.lower() in low:
                hits.append(where)
                return

    look(exe.name, exe.read_bytes())
    arc = CArchiveReader(str(exe))
    for name in arc.toc:
        data = arc.extract(name)
        if data is None:
            continue
        look("%s:%s" % (exe.name, name), data)
        if data[:4] == b"PYZ\0":
            pyz = arc.open_embedded_archive(name)
            for mod in pyz.toc:
                try:
                    co = pyz.extract(mod)
                except Exception:
                    continue
                if co is None or not hasattr(co, "co_filename"):
                    continue
                strs = []
                code_strings(co, strs)
                look("%s:%s:%s" % (exe.name, name, mod),
                     "\n".join(strs).encode("utf-8"))
    return hits


def neutral(stage):
    """The stage under a spare drive letter on Windows (subst), so no path
    in the build has the user's folder in it. (path, letter or None)"""
    if os.name != "nt":
        return stage, None
    for letter in "PQRSTUVWXY":
        if not os.path.exists(letter + ":\\"):
            r = subprocess.run(["subst", letter + ":", str(stage)])
            if r.returncode == 0:
                return Path(letter + ":\\"), letter
    print("no spare drive letter for subst: building in %s" % stage)
    return stage, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("PyInstaller isn't installed: pip install pyinstaller")
    out = Path(a.out)

    # Built from a copy in a neutral folder, so the compiled code's file
    # names are that folder's, never the repository's.
    real = Path(tempfile.mkdtemp(prefix="hp2pk-"))
    stage, letter = neutral(real)
    try:
        src = stage / "src"
        src.mkdir()
        for f in SOURCES:
            shutil.copy2(TOOLS / f, src / f)
        names = shutil.copy2(names_list(), src / "zdir_names_retail.txt")
        png, ico = make_icon(src)
        data = [names] + ([png] if png else [])
        gui = pyinstaller(stage, "hp2_packer_gui.pyw", GUI_NAME, True, ico,
                          data)
        cli = pyinstaller(stage, "hp2_packer.py", CLI_NAME, False, ico,
                          [names])

        hits = scan(gui) + scan(cli)
        if hits:
            for h in hits:
                print("names this computer: " + h)
            sys.exit("not written: the programs name this computer's user "
                     "or folders")

        if out.exists():
            shutil.rmtree(out)
        (out / "source").mkdir(parents=True)
        shutil.copy2(gui, out / gui.name)
        shutil.copy2(cli, out / cli.name)
        (out / "README.txt").write_text(README, encoding="utf-8",
                                        newline="\r\n")
        for f in SOURCES + ["zdir_names_retail.txt"] + \
                (["icon.png"] if png else []):
            shutil.copy2(src / f, out / "source" / f)
    finally:
        if letter:
            subprocess.run(["subst", letter + ":", "/D"])
        shutil.rmtree(real, ignore_errors=True)
    print("Built %s" % out)
    for p in sorted(out.iterdir()):
        if p.is_file():
            print("  %-26s %10d bytes" % (p.name, p.stat().st_size))


if __name__ == "__main__":
    main()
