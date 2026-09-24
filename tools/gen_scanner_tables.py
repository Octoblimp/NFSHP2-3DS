"""Emit the joystick's tables from NFSHP2.ELF.

    3DS Files/source/joyeventid.h   the JoyEvent and eButtonChars enums
    3DS Files/source/scannertab.c   ScannerConfigTable, ValidJoystick-
                                    ConfigurationTable, EventNameTable

Every button binding in the game is a row of ScannerConfigTable (0x002dc6c0,
231 x 32 bytes): which configurations it belongs to, the event it raises, the
scanner that reads it, and which bits of the DualShock 2 buffer it reads. The
table is data from end to end -- nothing in Joystick.obj knows what a button
is -- so the port carries it verbatim, and this script is the only thing that
writes it.

The enums come from the .mdebug stabs (docs/mdebug_raw_strings.txt), and the
script holds the image to them: every scanner pointer must be one of the
eleven Scanner_* functions, every event a JoyEvent value, every button glyph
an eButtonChars value, every EventNameTable string the enum's own name for
its value, and each count word (NumScannerConfigs gp-24344,
NumValidJoystickConfigurations gp-24340) the length of its table.

    python tools/gen_scanner_tables.py            # write both files
    python tools/gen_scanner_tables.py --check    # verify they are current
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mipsdis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "3DS Files", "source")
OUT_H = os.path.join(SRC, "joyeventid.h")
OUT_C = os.path.join(SRC, "scannertab.c")
STABS = os.path.join(ROOT, "docs", "mdebug_raw_strings.txt")

GP = 0x00328bf0
SCANNER_TABLE = 0x002dc6c0
SCANNER_COUNT = GP - 24344
VALID_TABLE = 0x002de3a0
VALID_COUNT = GP - 24340
NAME_TABLE = 0x002f22f8
NAME_ENTRIES = 127          # GetJoyEventName loops while i < 127 (0x0015151c)
SCANNER_SUFFIX = "__FP9EventNodePUiT1P13ScannerConfigP8Joystick"


def stabs_enum(name, last):
    """The longest stabs line defining enum `name` whose list reaches `last`
    -- the stabs are split over several lines and only one holds it all."""
    pat = re.compile(r"%s:t\d+=e([^;]*);" % re.escape(name))
    best = None
    with open(STABS, "r", encoding="latin-1") as fh:
        for ln in fh:
            for m in pat.finditer(ln):
                body = m.group(1)
                if last in body and (best is None or len(body) > len(best)):
                    best = body
    if best is None:
        sys.exit("no complete %s enum in %s" % (name, STABS))
    out = []
    for item in best.rstrip(",").split(","):
        k, v = item.split(":")
        out.append((k, int(v)))
    return out


def cstr(elf, addr):
    raw = elf.read(addr, 128)
    return raw[:raw.index(b"\0")].decode("latin-1")


def read_all():
    elf = mipsdis.Elf()
    events = stabs_enum("JoyEvent", "JOY_EVENT_SKIP:131")
    chars = stabs_enum("eButtonChars", "JOY_R:6")
    ev_name = {v: k for k, v in events}
    ch_name = {v: k for k, v in chars}
    if [v for _, v in events] != list(range(len(events))):
        sys.exit("JoyEvent is not 0..N in order")

    scanners = {}
    for sym, (addr, _) in elf.syms.items():
        if sym.startswith("Scanner_") and sym.endswith(SCANNER_SUFFIX):
            scanners[addr] = sym[:-len(SCANNER_SUFFIX)]
    if len(scanners) != 11:
        sys.exit("expected 11 scanners, found %d" % len(scanners))

    n = struct.unpack("<i", elf.read(SCANNER_COUNT, 4))[0]
    rows = []
    for i in range(n):
        r = elf.read(SCANNER_TABLE + 32 * i, 32)
        nums = list(struct.unpack("<8b", r[:8]))
        ev, sc = struct.unpack("<iI", r[8:16])
        x1, x2, s1, s2, param, dev, vdr, pad = struct.unpack("<8B", r[16:24])
        ch, nm = struct.unpack("<iI", r[24:32])
        if ev not in ev_name:
            sys.exit("row %d: event %d is not a JoyEvent" % (i, ev))
        if sc and sc not in scanners:
            sys.exit("row %d: scanner 0x%08x is not a Scanner_*" % (i, sc))
        if ch not in ch_name:
            sys.exit("row %d: glyph %d is not an eButtonChars" % (i, ch))
        if pad:
            sys.exit("row %d: padding byte 23 is %d" % (i, pad))
        rows.append(dict(nums=nums, ev=ev_name[ev],
                         sc=scanners[sc] if sc else None,
                         x1=x1, x2=x2, s1=s1, s2=s2, param=param, dev=dev,
                         vdr=vdr, ch=ch_name[ch],
                         name=cstr(elf, nm) if nm else None))
    if n != 231:
        sys.exit("NumScannerConfigs is %d, not 231" % n)

    nv = struct.unpack("<i", elf.read(VALID_COUNT, 4))[0]
    valid = []
    for i in range(nv):
        r = elf.read(VALID_TABLE + 20 * i, 20)
        typ = struct.unpack("<i", r[:4])[0]
        nums = list(struct.unpack("<10b", r[4:14]))
        six = list(struct.unpack("<6B", r[14:20]))
        valid.append((typ, nums, six))
    if nv != 7:
        sys.exit("NumValidJoystickConfigurations is %d, not 7" % nv)

    names = []
    for i in range(NAME_ENTRIES):
        ev, p = struct.unpack("<iI", elf.read(NAME_TABLE + 8 * i, 8))
        s = cstr(elf, p)
        if ev_name.get(ev) != s:
            sys.exit("EventNameTable[%d] names %d %r, the enum says %r"
                     % (i, ev, s, ev_name.get(ev)))
        names.append(ev_name[ev])
    return events, chars, rows, valid, names


def c_string(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def render_h(events, chars):
    ev = "\n".join("    %s = %d," % (k, v) for k, v in events)
    ch = "\n".join("    %s = %d," % (k, v) for k, v in chars)
    return """\
// Generated by tools/gen_scanner_tables.py -- do not edit.
//
// The JoyEvent and eButtonChars enums, from the .mdebug stabs. JoyEvent is
// the event a handler is registered for and a ScannerConfig row raises;
// eButtonChars is the glyph code the font draws for a button's name.

#ifndef JOYEVENTID_H
#define JOYEVENTID_H

#include <stdint.h>

typedef int32_t JoyEvent;

enum {
%s
};

#define JOY_EVENT_COUNT %d

enum {
%s
};

#endif
""" % (ev, len(events), ch)


def render_c(rows, valid, names):
    out = []
    for i, r in enumerate(rows):
        nums = ", ".join("%d" % v for v in r["nums"])
        out.append(
            "    { { %s }, %s,\n"
            "      %s, %d, %d, %d, %d, %d, %d, %d,\n"
            "      %s, %s },  // %d"
            % (nums, r["ev"], r["sc"] or "NULL", r["x1"], r["x2"], r["s1"],
               r["s2"], r["param"], r["dev"], r["vdr"], r["ch"],
               c_string(r["name"]) if r["name"] is not None else "NULL", i))
    vrows = []
    for typ, nums, six in valid:
        vrows.append("    { %d, { %s }, %s },"
                     % (typ, ", ".join("%d" % v for v in nums),
                        ", ".join("%d" % v for v in six)))
    nrows = "\n".join('    { %s, "%s" },' % (n, n) for n in names)
    return """\
// Generated by tools/gen_scanner_tables.py -- do not edit.
//
// ScannerConfigTable (0x002dc6c0), ValidJoystickConfigurationTable
// (0x002de3a0) and EventNameTable (0x002f22f8), read out of NFSHP2.ELF.
// A scanner row is
//
//     { configurations }, event,
//     scanner, Xor1, Xor2, Shift1, Shift2, Param, AnalogDevice, ValidInReplay,
//     glyph, button name
//
// and docs/formats/joystick.md has what the bit numbers mean.

#include <stddef.h>
#include <stdint.h>

#include "joyevent.h"

const ScannerConfig ScannerConfigTable[] = {
%s
};

const int32_t NumScannerConfigs =
    (int32_t)(sizeof(ScannerConfigTable) / sizeof(ScannerConfigTable[0]));

// { type, { configurations }, steer hyst, steer dz, throttle hyst,
//   throttle dz, brake hyst, brake dz }
const ValidJoystickConfiguration ValidJoystickConfigurationTable[] = {
%s
};

const int32_t NumValidJoystickConfigurations =
    (int32_t)(sizeof(ValidJoystickConfigurationTable)
              / sizeof(ValidJoystickConfigurationTable[0]));

// Five events have no row: MENU_R1, MENU_R2, CARSEL_ORBIT_IN,
// CARSEL_ORBIT_OUT and DIRECTION.
const EventName EventNameTable[JOY_EVENT_NAMES] = {
%s
};
""" % ("\n".join(out), "\n".join(vrows), nrows)


def main():
    events, chars, rows, valid, names = read_all()
    outs = [(OUT_H, render_h(events, chars)), (OUT_C, render_c(rows, valid, names))]
    check = "--check" in sys.argv
    stale = 0
    for path, text in outs:
        old = None
        if os.path.exists(path):
            with open(path, "r", newline="") as fh:
                old = fh.read()
        base = os.path.basename(path)
        if check:
            if old == text:
                print("%s is up to date" % base)
            else:
                print("%s is STALE -- re-run tools/gen_scanner_tables.py" % base)
                stale = 1
            continue
        with open(path, "w", newline="") as fh:
            fh.write(text)
        print("wrote %s (%d bytes)" % (path, len(text)))
    return stale


if __name__ == "__main__":
    sys.exit(main())
