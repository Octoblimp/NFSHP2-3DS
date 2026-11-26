# The PS2 releases

The port was made from the European disc, SLES-50731, and the Packer makes
the SD card's files from any of the game's PS2 releases:

| Release | Boot program | Video | Install |
|---|---|---|---|
| USA, SLUS-20362 | `SLUS_203.62` | NTSC | known |
| Europe v1.00, SLES-50731 | `SLES_507.31` | PAL | known (the disc the port was made from) |
| Europe v2.00, SLES-50731 | `SLES_507.31` | PAL | known |
| Asia, SLPM-65181 | `SLPM_651.81` | NTSC | known |
| Korea, SLPM-67527 | `SLPM_675.27` | NTSC | known |

`tools/release.py` has the boot programs' SHA-1s. The Packer
(`tools/hp2_packer.py`) reads `SYSTEM.CNF`'s `BOOT2` line, hashes that
program, and names the release in its log and in `NFSHP2/RELEASE.TXT`. A
disc booting one of these names with another hash is packed anyway, with a
line saying so. Another boot name is refused. A folder holding only
`ZDIR.BIN` and `ZZDATA.BIN` can't be named, and is packed by `PAL.TAG`
alone.

## Why one port runs them all

All five discs run the same game program:
- USA and Europe v1.00 boot identical bytes.
- Europe v2.00 differs only in two screens' stack frames: the Points
  Rewards and Task Rewards screens (retail `0x001de568` and `0x001de6a8`)
  have 128 bytes more for their text. The port's two screens format into
  256-byte buffers (`endresults.c`), so a long blurb is never cut short.
- Asia and Korea are the same code linked again with their own product
  numbers. Their text is the same six languages, in English by default.
  There are no Japanese or Korean strings or fonts, and the buttons are not
  swapped.

The port runs on its own C and reads only the data, so the program's
differences don't reach it.

## What differs in the data

The ZDIR directory (`docs/zdir_names_retail.txt`, the v1.00 disc's) is the
base. The other discs differ from it by a few entries:
- **PAL.TAG**, empty, only on the European discs.
- **HOTCHUNK.TAG**, a build leftover the game never reads, only on v2.00.
- **Two attract-mode replays** are missing from v2.00, Asia and Korea.
  `dmreplay_consider_launching` already skips a replay it can't find.
- **Files that differ by a few bytes**: about 150 on v2.00, about 50 on
  Asia and Korea (the archive was built again). Files are found by name
  hash, so the Packer takes each disc's own.

`release.compare_directory` refuses a disc only if it lacks a named file
outside `REPLAY\` other than `PAL.TAG`. Entries the list doesn't know are
left out.

## PAL and NTSC

The PS2 game picks its video mode with `bFileExists("PAL.TAG")`.
- **PAL** asks for a language at every start, and Options has a Languages
  item.
- **NTSC** plays in English, and Options hides the Languages item
  (`bscreens.c`).

The port does the same: `gamedata_video_mode()`. `make_card.py` keeps
`PAL.TAG` and writes `RELEASE.TXT`, and deletes a `PAL.TAG` left on the card
by a European disc when it copies an NTSC one. A card with neither file is
from before this support, when only the PAL disc was packed, so it stays
PAL.

The port keeps its own frame timing, so 50 against 60 Hz changes nothing
else. Saves are the port's own, in `NFSHP2/SAVES`, and the same for every
release.

## Checked on the discs (2026-11-26)

All five ISOs went through the Packer (`tools/hp2_packer.py`, under
Python 3.12). Each was named by its SHA-1, and each `SYSTEM.CNF` says
`VMODE = NTSC` or `PAL` as the table above does:
- **Europe v1.00 and v2.00:** `RELEASE.TXT` says PAL, and the card has
  `PAL.TAG` (301 files, 2.76 GB).
- **USA, Asia and Korea:** `RELEASE.TXT` says NTSC, and the card has no
  `PAL.TAG` (300 files).
- **USA packed over a Europe v1.00 card:** the old `PAL.TAG` is deleted.
- **`make_card.py` on its own** (no disc to read) writes `RELEASE.TXT`
  with the release unknown and the video mode from `PAL.TAG`.
- **A disc drive's layout** (`SYSTEM.CNF` and the boot program in the
  root, `ZDIR.BIN` and `ZZDATA.BIN` in `NFSHP2/`) reads the same as the
  image.

Every ZDIR entry was compared with v1.00's, unpacked:
- **USA:** the same bytes as v1.00, without `PAL.TAG`.
- **Asia and Korea:** identical to each other. 46 files change 3 to 1,900
  bytes inside the same sizes: the menus, the global bundles and the tracks.
  The language files are v1.00's, byte for byte: there is no Japanese or
  Korean text.
- **v2.00:** 147 files change. The menus, global bundles and tracks change
  as on Asia and Korea, and so do the car models (a few dozen bytes each).
  In the language files only a stale header pointer changes, not the text.

The game's side (`gamedata_video_mode()`, the 256-byte reward texts) is
the same C as the Linux handheld port (manuelpllull/NFSHP2-R36S), where
USA, Korea and Europe v1.00 installs were played to a race: NTSC boots
straight to the title with no language screen, PAL opens on the language
screen as before, and an install without `RELEASE.TXT` boots as PAL. The
3DS build compiles with it; it hasn't been run on a 3DS from an NTSC disc
yet.
