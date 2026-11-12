NFSHP2-3DS Packer
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

  nfshp2-packer --disc "<disc image or drive>" --card E:\
  nfshp2-packer --disc D:\ --card "<folder>" --keep-work --prune
  nfshp2-packer --help     every option

source/ holds the Python both programs are built from. With Python 3.8 or
newer installed, the same runs without the .exe files:

  python source/hp2_packer_gui.pyw
  python source/hp2_packer.py --disc ... --card ...

and `python source/build_packer.py` (with PyInstaller) builds this folder
again. In the NFSHP2-3DS repository they are in tools/, and the README's
Installing section has the step-by-step Python commands as well.
