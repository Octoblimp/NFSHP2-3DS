#!/usr/bin/env python3
r"""Decode `SOUND\ENGINE.CTB` and `SOUND\ENGINE.LTB`, the engine crossfade tables.

These two files are the whole of the player car's engine sound. Between them
they hold twelve looping samples and, for each one, a 512-entry curve saying
how loud it should be at a given engine speed. The runtime crossfades all
twelve every frame; that is the engine note.

`PlayerEngineSound::Init` loads them into `definitions[0]` (`.CTB`) and
`definitions[1]` (`.LTB`), and both are the same 6504-byte format:

    off     what
    0       EngineDef                 360 bytes, `docs/mdebug_structs.txt`
    360     EngineDefEntry xlate[12]  512 signed bytes each

`EngineDef` is:

    off     type            field
    0       char[4]         id                     always `CRDl`
    4       u8              ver                    always 2
    5       u8              resolved               0 on disc, set at load
    6       u8              startevent
    7       u8              controllerpercent      always 100
    8       s16             lowrandomtargetlevel   } the idle wobble the
    10      s16             lowrandomtargetrange   } engine gets when the
    12      s32             lowrandomattacktime    } car is sitting still
    16      s32             lowrandomattackrange   }
    20      s16             highrandomtargetlevel  } and the same at speed
    22      s16             highrandomtargetrange
    24      s32             highrandomattacktime
    28      s32             highrandomattackrange
    32      s8[8]           patchnum               sample index, -1 = unused
    40      EngineDefEvent  event[16]              all zero on disc
    296     u32[8]          pvoltable              -> volume curve
    328     u32[8]          pbendtable             -> pitch bend curve

The two pointer arrays are stored **self-relative**: entry `i` holds a byte
offset from its own address, so the target is `base + 4 * i + value`, and a
zero means "no table". `PlayerEngineSound::ResolveTables` (`0x001fd9c8`)
turns them into real pointers in place (`*p += (uintptr_t)p`) and sets
`resolved` so it only happens once. Every shipped file resolves to
`pvoltable[i] -> block 2 * i` and `pbendtable[i] -> block 2 * i + 1`.

## The eight slots

`patchnum` is an index into a fixed name table that lives in the ELF's
`.sdata` at `0x00324910`, twelve four-character names:

    0  lelo   1  lemd   2  lehi   3  lxlo   4  lxmd   5  lxhi
    6  ceid   7  cemd   8  cehi   9  cxid  10  cxmd  11  cxhi

which decode as **l**oad / **c**oast, **e**ngine mic / e**x**haust mic, then
the RPM band -- lo/md/hi, or id/md/hi for the coast set, whose bottom band is
idle. So `.LTB` is the **L**oad table (on throttle) with patches 0-5 and
`.CTB` the **C**oast table (off throttle) with patches 6-11; each holds three
RPM bands heard through two microphones. Slots 3 and 7 are unused in the
shipped data, leaving room for a fourth band per mic.

The slot order is `[engine lo, engine md, engine hi, -, exhaust lo, exhaust
md, exhaust hi, -]`, and slots 4-6 carry curves byte-identical to slots 0-2:
the two mics share a crossfade, only the samples differ.

## How a curve is used

`PlayerEngineSound::UpdateEngine` (`0x001fdfd0`) walks voices 0..15, taking
`definitions[voice >> 3]` and slot `voice & 7`, and for each one does

    level  = min(440, 440 * CurrentRPM / MaxRPM)        0..440
    v      = pvoltable[slot][level] * Volume >> 7
    v      = v * CrossFade[throttle ? r : 127 - r] >> 7   r = throttle * 127
    v      = min(127, v * 5 / 4)
    v      = v * CrossFade[exhaust ? t : 127 - t] >> 7    t = Timbre

so the 512-entry curve is indexed by engine speed scaled to 0..440 -- the
last 71 entries are never reached, and the shipped curves duly stop at 441.
`CrossFade` is a static 128-entry equal-power table at `0x003137b0`
(`CrossFade[i] ~= 127 * sqrt(i / 127)`) used twice: once to blend `.CTB`
against `.LTB` by throttle position, and once to blend engine mic against
exhaust mic by `Timbre`. Which of the two a voice gets is decided by the
second letter of its patch name -- `ActivateSound` does a literal
`name[1] ^ 'x'` and caches the answer per voice.

`pbendtable` is resolved but never read: nothing in `CarSoundEngine.obj`
touches offset 328. Pitch comes from `EngineSample.detune` and the
`CentsToPitch` table at `0x00313838` instead. The bend curves are still
authored and still sane -- monotonic ramps inside each band's window -- so
they are dumped here for completeness.

Usage:
    engine_table.py extracted/SOUND/ENGINE.LTB            summary + curves
    engine_table.py extracted/SOUND/*.?TB --plot          taller ASCII plot
    engine_table.py extracted/SOUND/ENGINE.CTB --csv out.csv
"""

import argparse
import os
import struct
import sys

MAGIC = b"CRDl"
HEADER_SIZE = 360
BLOCK_SIZE = 512
NUM_SLOTS = 8
PVOLTABLE = 296
PBENDTABLE = 328

# .sdata 0x00324910 -- load/coast, engine/exhaust mic, then the RPM band.
PATCH_NAMES = ["lelo", "lemd", "lehi", "lxlo", "lxmd", "lxhi",
               "ceid", "cemd", "cehi", "cxid", "cxmd", "cxhi"]
BAND = {"lo": "low", "md": "mid", "hi": "high", "id": "idle"}

# min(440, 440 * CurrentRPM / MaxRPM) -- the highest index the runtime reaches.
MAX_LEVEL = 440


def patch_name(n):
    return PATCH_NAMES[n] if 0 <= n < len(PATCH_NAMES) else "?"


def describe(n):
    """Spell out what a patch number means."""
    s = patch_name(n)
    if s == "?":
        return "unknown patch %d" % n
    return "%s %s, %s rpm" % ("load" if s[0] == "l" else "coast",
                              "exhaust" if s[1] == "x" else "engine",
                              BAND.get(s[2:], s[2:]))


class EngineDef(object):
    def __init__(self, buf, path=None):
        self.path = path
        self.raw = buf
        if len(buf) < HEADER_SIZE or buf[:4] != MAGIC:
            raise ValueError("not an engine table (magic %r)" % buf[:4])
        self.ver, self.resolved, self.startevent, self.controllerpercent = buf[4:8]
        f = struct.unpack_from("<hhiihhii", buf, 8)
        self.low = f[:4]
        self.high = f[4:]
        self.patchnum = list(struct.unpack_from("<8b", buf, 32))
        self.event = [struct.unpack_from("<4BhhiI", buf, 40 + 16 * i)
                      for i in range(16)]
        self.vol = [self._table(PVOLTABLE, i) for i in range(NUM_SLOTS)]
        self.bend = [self._table(PBENDTABLE, i) for i in range(NUM_SLOTS)]

    def _table(self, base, i):
        """Follow one self-relative pointer to its 512-byte curve.

        Returns (block index, curve), or None where the pointer is null.
        """
        at = base + 4 * i
        off, = struct.unpack_from("<I", self.raw, at)
        if off == 0:
            return None
        start = at + off
        if start + BLOCK_SIZE > len(self.raw) or (start - HEADER_SIZE) % BLOCK_SIZE:
            raise ValueError("table %d resolves to a bad offset 0x%x" % (i, start))
        return ((start - HEADER_SIZE) // BLOCK_SIZE,
                list(self.raw[start:start + BLOCK_SIZE]))

    def slots(self):
        """(slot, patchnum, volume table, bend table) for each used slot."""
        for i, p in enumerate(self.patchnum):
            if p >= 0:
                yield i, p, self.vol[i], self.bend[i]


def window(curve):
    """The index range over which a curve is audible."""
    nz = [i for i, v in enumerate(curve) if v]
    return (nz[0], nz[-1]) if nz else None


def sparkline(curve, width, height):
    """Plot a curve as `height` rows of `width` columns."""
    step = max(1, (MAX_LEVEL + 1) // width)
    cols = [max(curve[i:i + step]) for i in range(0, MAX_LEVEL + 1, step)]
    if height == 1:
        glyph = " .:-=+*#@"
        return ["".join(glyph[min(len(glyph) - 1, c * len(glyph) // 128)] for c in cols)]
    rows = []
    for r in range(height, 0, -1):
        hi = 128 * r // height
        lo = 128 * (r - 1) // height
        rows.append("".join("#" if c >= hi else "+" if c > lo else " " for c in cols))
    return rows


def report(defn, plot, out):
    name = os.path.basename(defn.path or "?")
    kind = "load (on throttle)" if name.upper().endswith(".LTB") else \
           "coast (off throttle)" if name.upper().endswith(".CTB") else "?"
    out("== %s -- %s, %d bytes ==" % (name, kind, len(defn.raw)))
    out("id %s  ver %d  resolved %d  startevent %d  controllerpercent %d"
        % (defn.raw[:4].decode("ascii"), defn.ver, defn.resolved,
           defn.startevent, defn.controllerpercent))
    for label, v in (("low ", defn.low), ("high", defn.high)):
        out("%srandom  targetlevel %-5d targetrange %-5d attacktime %-6d attackrange %d"
            % (label, v[0], v[1], v[2], v[3]))
    used = [e for e in defn.event if e[0]]
    out("event[16]: %s" % ("all unused" if not used else
        "; ".join("use %d pat %d delta %d max %d attack %d decay %d"
                  % (e[0], e[1], e[4], e[5], e[6], e[7]) for e in used)))
    out("")
    height = 6 if plot else 1
    width = 64
    for slot, p, vol, bend in defn.slots():
        for label, table in (("vol", vol), ("bend", bend)):
            if table is None:
                out(" slot %d %-4s: absent" % (slot, label))
                continue
            block, curve = table
            w = window(curve)
            head = (" slot %d patch %-2d %-4s block %-2d  %-26s"
                    % (slot, p, label, block, describe(p)))
            tail = ("silent" if w is None else
                    "level %d..%d  peak %d" % (w[0], w[1], max(curve)))
            rows = sparkline(curve, width, height)
            out("%s %s" % (head, tail))
            for row in rows:
                out("      |%s|" % row)
        out("")
    unused = [i for i, p in enumerate(defn.patchnum) if p < 0]
    out(" slots %s unused; level index is min(%d, %d * rpm / maxrpm)"
        % (", ".join(str(i) for i in unused) or "none", MAX_LEVEL, MAX_LEVEL))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", nargs="+", help="ENGINE.CTB / ENGINE.LTB")
    ap.add_argument("--plot", action="store_true",
                    help="draw the curves six rows tall instead of one")
    ap.add_argument("--csv", help="write every curve to this CSV instead")
    a = ap.parse_args()

    defs = []
    for path in a.file:
        with open(path, "rb") as fh:
            defs.append(EngineDef(fh.read(), path))

    if a.csv:
        import csv
        cols = []
        for d in defs:
            tag = os.path.splitext(os.path.basename(d.path))[0].lower()
            for slot, p, vol, bend in d.slots():
                for label, table in (("vol", vol), ("bend", bend)):
                    if table is not None:
                        cols.append(("%s.%s.%s" % (tag, patch_name(p), label),
                                     table[1]))
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["level"] + [c[0] for c in cols])
            for i in range(BLOCK_SIZE):
                w.writerow([i] + [c[1][i] for c in cols])
        print("wrote %s -- %d levels x %d curves" % (a.csv, BLOCK_SIZE, len(cols)))
        return 0

    for i, d in enumerate(defs):
        if i:
            print("")
        report(d, a.plot, print)
    return 0


if __name__ == "__main__":
    sys.exit(main())
