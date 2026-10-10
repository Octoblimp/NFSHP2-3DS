"""Emit 3DS Files/source/bsndtab.c from two tables in the retail image.

The first is bSnd_nArraydBPanTable, 256 unsigned 16-bit entries at
0x00322830 (the demo disc's 0x00317d00, the same bytes), and the only lookup
in the whole bSnd driver. `GetVolumesFromPan` (0x0024d928) reads it twice:

    left  = (volume * bSnd_nArraydBPanTable[pan + 127]) >> 14
    right = (volume * bSnd_nArraydBPanTable[127 - pan]) >> 14

so with pan held to -127..+127 by GetPanFromAzimuth only entries 0..254 are
ever reached; entry 255 is padding. Full scale is 16383, not 16384, which is
why a centred sound comes out at 0.7114 rather than 0.7071 -- see below.

Entries 0..224 are exactly floor(16383 * cos(i * pi / 512)), a constant-power
law sampled over the first 225/256 of a quarter turn, and this script checks
that they still are, so a bad read of the ELF cannot pass silently.

Entries 225..255 are not on that curve: they carry an extra attenuation that
steps down every four entries -- -1.11 dB, -2.23, -4.68, -7.14, -13.10,
-19.07, -25.1, then the last three -- which drags the far edge from the
cosine's -20 dB down to -78 dB, i.e. to silence. No formula has been found
for the taper and it looks hand-tuned, so the file carries all 256 entries
verbatim and the check covers the part that does regenerate. That is the same
arrangement bSinTable gets in gen_bmath_tables.py, and for the same reason.

The second is the FrontendSoundEvent table at 0x002fb098, which fesound.c's
MakeFrontendSound indexes: 31 records of an id, the region (0 common, 1
"FrontEnd"), the sample's name and the bSample the init functions store.

    python tools/gen_bsnd_tables.py            # write the file
    python tools/gen_bsnd_tables.py --check    # verify it is up to date
"""
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mipsdis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "3DS Files", "source", "bsndtab.c")
RETAIL = os.path.join(ROOT, "PS2 Files", "Full Game", "SLES_507.31")

PAN_TABLE = 0x00322830       # bSnd_nArraydBPanTable, 256 x u16
PAN_FULL = 16383             # the table's own maximum, and its entry 0
COSINE_ENTRIES = 225         # 0..224 regenerate; 225..255 are the taper


def read_table():
    elf = mipsdis.Elf(RETAIL)
    table = list(struct.unpack("<256H", elf.read(PAN_TABLE, 512)))

    for i in range(COSINE_ENTRIES):
        want = int(PAN_FULL * math.cos(i * math.pi / 512.0))
        if table[i] != want:
            sys.exit("bSnd_nArraydBPanTable[%d] is %d, but the constant-power "
                     "curve says %d -- the ELF read is wrong, or the table is "
                     "not the one this script documents" % (i, table[i], want))
    if table[COSINE_ENTRIES] == int(PAN_FULL * math.cos(COSINE_ENTRIES * math.pi / 512.0)):
        sys.exit("bSnd_nArraydBPanTable[%d] is on the cosine after all -- the "
                 "taper starts somewhere else and the comments are stale"
                 % COSINE_ENTRIES)
    return table


SOUND_EVENTS = 0x002fb098    # the FrontendSoundEvent table, 16 bytes each
SOUND_EVENT_COUNT = 31       # every loop over it runs while i < 31 (0x0016df3c)


def read_events():
    """The table MakeFrontendSound indexes (0x0016e038): one record per
    FrontendSoundEvent -- its id, which region the sample comes from, its
    name and the bSample. `fromFrontEnd` is what InitGlobalMenuSound
    (0x0016ded8) and InitFrontendSounds (0x0016df60) test to take the entry
    from CommonRegion or from Region("FrontEnd")."""
    elf = mipsdis.Elf(RETAIL)
    out = []
    for i in range(SOUND_EVENT_COUNT):
        rec = elf.read(SOUND_EVENTS + i * 16, 16)
        ident, fromFE, nameAddr, sample = struct.unpack("<4I", rec)
        if sample:
            sys.exit("event %d already has a bSample in the image at %08x -- "
                     "this is not the table this script documents" % (i, sample))
        if ident != i or fromFE not in (0, 1):
            sys.exit("event %d reads id %d, region %d -- this is not the "
                     "table this script documents" % (i, ident, fromFE))
        if nameAddr:
            raw = elf.read(nameAddr, 64)
            name = raw[:raw.index(b"\0")].decode("latin-1")
        else:
            name = None
        out.append((ident, name, fromFE))
    # Event 0 is the "no sound" slot every callback leaves in place, and the
    # engine indexes this table with it. If it ever names a patch, silence has
    # stopped being free and every caller needs looking at.
    if out[0][1] is not None:
        sys.exit("FrontendSoundEvent 0 names %r -- it is meant to be silence"
                 % out[0][1])
    return out


def rows(values, per, fmt):
    out = []
    for i in range(0, len(values), per):
        out.append("    " + " ".join(fmt % v for v in values[i:i + per]))
    return "\n".join(out)


def event_rows(events):
    out = []
    for ident, name, fromFE in events:
        text = '"%s"' % name if name is not None else "NULL"
        out.append("    { %2d, %d, %s }," % (ident, fromFE, text))
    return "\n".join(out)


def render():
    table = read_table()
    events = read_events()
    return """\
// Generated by tools/gen_bsnd_tables.py -- do not edit.
//
// bSnd_nArraydBPanTable, read out of SLES_507.31 at 0x00322830. Entries 0..224
// are floor(16383 * cos(i * pi / 512)); 225..255 add a hand-tuned taper that
// takes the far edge down to silence. docs/formats/sound-driver.md has the
// numbers; the generator re-checks the cosine half every time it runs.

#include <stddef.h>
#include <stdint.h>

#include "fesound.h"

const uint16_t bsnd_pan_table[256] = {
%s
};

// The FrontendSoundEvent table at 0x002fb098, which MakeFrontendSound
// indexes straight (0x0016e038): the id, the region (0 the common one, 1
// "FrontEnd") and the sample's name. Entry 0 is silence.
const FeSoundEntry fesound_events[FESOUND_EVENT_COUNT] = {
%s
};
""" % (rows(table, 8, "%6d,"), event_rows(events))


def main():
    text = render()
    check = "--check" in sys.argv
    old = None
    if os.path.exists(OUT):
        with open(OUT, "r", newline="") as fh:
            old = fh.read()
    if check:
        if old == text:
            print("bsndtab.c is up to date")
            return 0
        print("bsndtab.c is STALE -- re-run tools/gen_bsnd_tables.py")
        return 1
    with open(OUT, "w", newline="") as fh:
        fh.write(text)
    print("wrote %s (%d bytes)" % (OUT, len(text)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
