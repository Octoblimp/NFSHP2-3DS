"""Emit the joystick's tables from retail's SLES_507.31.

    3DS Files/source/joyeventid.h   the JoyEvent and eButtonChars enums
    3DS Files/source/scannertab.c   ScannerConfigTable, ValidJoystick-
                                    ConfigurationTable, EventNameTable

Every button binding in the game is a row of ScannerConfigTable (0x002dc500,
230 x 36 bytes): which configurations it belongs to, the event it raises, the
scanner that reads it, which bits of the DualShock 2 buffer it reads, and the
one or two glyphs and the name the options screen shows for it. The table is
data from end to end -- nothing in Joystick.obj knows what a button is -- so
the port carries it verbatim, and this script is the only thing that writes
it.

Retail has no stabs, so the enums start from the demo's (NFSHP2.ELF's .mdebug,
docs/mdebug_raw_strings.txt) and take retail's changes:

  - JoyEvent gains REPLAY_ERASE_DEMO at 110, after REPLAY_TEST_DEMO, so every
    event from STEER on is one higher than the demo's; and 133..148, which
    retail neither names nor gives a row name to: the main menu's code reader
    (NewMainMenu, 0x0024f488) registers all sixteen, one per button. The port
    calls them JOY_EVENT_CHEAT_<the row's button name>.
  - eButtonChars loses the demo's LEFT_ANALOG (144) and RIGHT_ANALOG (145):
    retail's 144..157 are the sticks' directions, the D-pad and the wheel's,
    named here by what BUTTONSOUT draws for each (146 is the apostrophe).

and the script holds the image to them: every scanner pointer must be one of
the eleven Scanner_* functions (by retail_syms.txt's placement), every event a
JoyEvent value, every glyph an eButtonChars value, every EventNameTable string
the enum's own name for its value, and each count word (NumScannerConfigs
gp-23824, NumValidJoystickConfigurations gp-23820) the length of its table.

    python tools/gen_scanner_tables.py            # write both files
    python tools/gen_scanner_tables.py --check    # verify they are current
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mipsdis
import retaildis

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "3DS Files", "source")
OUT_H = os.path.join(SRC, "joyeventid.h")
OUT_C = os.path.join(SRC, "scannertab.c")
STABS = os.path.join(ROOT, "docs", "mdebug_raw_strings.txt")

GP = retaildis.GP
SCANNER_TABLE = 0x002dc500
SCANNER_COUNT = GP - 23824
SCANNER_STRIDE = 36
VALID_TABLE = 0x002de558
VALID_COUNT = GP - 23820
NAME_TABLE = 0x002fa2d0
NAME_ENTRIES = 130          # GetJoyEventName loops while i < 130 (0x00154564)
SCANNER_SUFFIX = "__FP9EventNodePUiT1P13ScannerConfigP8Joystick"

# Retail's one new named event, and where it goes.
ERASE_DEMO = ("JOY_EVENT_REPLAY_ERASE_DEMO", 110)
# The code reader's events, 133.., by the button each row reads.
CHEAT_BUTTONS = ["L1", "L2", "R1", "R2", "DPADL", "DPADR", "SQUARE",
                 "TRIANGLE", "L3", "R3", "DPADU", "DPADD", "START", "SELECT",
                 "CROSS", "CIRCLE"]
CHEAT_FIRST = 133
# Retail's glyphs from 144, by BUTTONSOUT's cell for each.
RETAIL_CHARS = [
    ("JOY_LSTICK_UPDOWN", 144),     # 'p'
    ("JOY_LSTICK_UP", 145),         # 'v'
    ("JOY_LSTICK_DOWN", 147),       # 'u'
    ("JOY_LSTICK_LEFTRIGHT", 148),  # 'q', STEER_ANALOG's
    ("JOY_RSTICK_UPDOWN", 149),     # 'r'
    ("JOY_RSTICK_UP", 150),         # 't', THROTTLE_ANALOG_ALTERNATE's
    ("JOY_RSTICK_DOWN", 151),       # 's', BRAKE_ANALOG_ALTERNATE's
    ("JOY_RSTICK_LEFTRIGHT", 152),  # 'c'
    ("JOY_DPAD_ROUND", 153),        # 'x', the wheel's D-pad STEER
    ("JOY_DPAD", 154),              # '2', the digital pad's D-pad STEER
    ("JOY_WHEEL", 155),             # 'y'
    ("JOY_GAS_PEDAL", 156),         # 'z'
    ("JOY_BRAKE_PEDAL", 157),       # '1'
]
DEMO_ONLY_CHARS = ("JOY_LEFT_ANALOG", "JOY_RIGHT_ANALOG")


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


def retail_events():
    demo = stabs_enum("JoyEvent", "JOY_EVENT_SKIP:131")
    if [v for _, v in demo] != list(range(len(demo))):
        sys.exit("the demo's JoyEvent is not 0..N in order")
    name, at = ERASE_DEMO
    events = [(k, v if v < at else v + 1) for k, v in demo]
    events.insert(at, (name, at))
    events += [("JOY_EVENT_CHEAT_" + b, CHEAT_FIRST + i)
               for i, b in enumerate(CHEAT_BUTTONS)]
    if [v for _, v in events] != list(range(len(events))):
        sys.exit("retail's JoyEvent is not 0..N in order")
    return events


def retail_chars():
    demo = stabs_enum("eButtonChars", "JOY_R:6")
    chars = [(k, v) for k, v in demo if k not in DEMO_ONLY_CHARS]
    if len(chars) != len(demo) - len(DEMO_ONLY_CHARS):
        sys.exit("the demo's eButtonChars has no %s" % (DEMO_ONLY_CHARS,))
    # Keep the stabs' order: the PS2 buttons, then the new, then the I/II/A/B
    # of the other pads.
    last_ps2 = max(i for i, (_, v) in enumerate(chars) if v >= 128)
    return chars[:last_ps2 + 1] + RETAIL_CHARS + chars[last_ps2 + 1:]


def read_all():
    elf = mipsdis.Elf(str(retaildis.RETAIL))
    retaildis.load(elf, retaildis.SYMS)
    events = retail_events()
    chars = retail_chars()
    ev_name = {v: k for k, v in events}
    ch_name = {v: k for k, v in chars}

    scanners = {}
    for sym, (addr, _) in elf.syms.items():
        if sym.startswith("Scanner_") and sym.endswith(SCANNER_SUFFIX):
            scanners[addr] = sym[:-len(SCANNER_SUFFIX)]
    if len(scanners) != 11:
        sys.exit("expected 11 scanners, found %d" % len(scanners))

    n = struct.unpack("<i", elf.read(SCANNER_COUNT, 4))[0]
    rows = []
    for i in range(n):
        r = elf.read(SCANNER_TABLE + SCANNER_STRIDE * i, SCANNER_STRIDE)
        nums = list(struct.unpack("<8b", r[:8]))
        ev, sc = struct.unpack("<iI", r[8:16])
        x1, x2, s1, s2, param, dev, vdr, pad = struct.unpack("<8B", r[16:24])
        ch, ch2, nm = struct.unpack("<iiI", r[24:36])
        if ev not in ev_name:
            sys.exit("row %d: event %d is not a JoyEvent" % (i, ev))
        if sc and sc not in scanners:
            sys.exit("row %d: scanner 0x%08x is not a Scanner_*" % (i, sc))
        for c in (ch, ch2):
            if c not in ch_name:
                sys.exit("row %d: glyph %d is not an eButtonChars" % (i, c))
        if pad:
            sys.exit("row %d: padding byte 23 is %d" % (i, pad))
        name = cstr(elf, nm) if nm else None
        if ev >= CHEAT_FIRST and ev_name[ev] != "JOY_EVENT_CHEAT_%s" % name:
            sys.exit("row %d: event %d reads %r" % (i, ev, name))
        rows.append(dict(nums=nums, ev=ev_name[ev],
                         sc=scanners[sc] if sc else None,
                         x1=x1, x2=x2, s1=s1, s2=s2, param=param, dev=dev,
                         vdr=vdr, ch=ch_name[ch], ch2=ch_name[ch2],
                         name=name))
    if n != 230:
        sys.exit("NumScannerConfigs is %d, not 230" % n)

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
    unnamed = [k for k, v in events if k not in names and v < CHEAT_FIRST]
    return events, chars, rows, valid, names, unnamed


def c_string(s):
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def render_h(events, chars):
    ev = "\n".join("    %s = %d," % (k, v) for k, v in events)
    ch = "\n".join("    %s = %d," % (k, v) for k, v in chars)
    return """\
// Generated by tools/gen_scanner_tables.py -- do not edit.
//
// The JoyEvent and eButtonChars enums, retail's. JoyEvent is the event a
// handler is registered for and a ScannerConfig row raises; eButtonChars is
// the glyph code the font draws for a button's name. Both start from the
// demo's .mdebug stabs: retail adds REPLAY_ERASE_DEMO at 110, moving every
// event from STEER on up one, and the main menu's code reader's sixteen
// unnamed events at 133 (the CHEAT_ names are the port's); and retail's
// glyphs from 144 are the sticks' directions, the D-pad and the wheel's.

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


def render_c(rows, valid, names, unnamed):
    out = []
    for i, r in enumerate(rows):
        nums = ", ".join("%d" % v for v in r["nums"])
        out.append(
            "    { { %s }, %s,\n"
            "      %s, %d, %d, %d, %d, %d, %d, %d,\n"
            "      %s, %s, %s },  // %d"
            % (nums, r["ev"], r["sc"] or "NULL", r["x1"], r["x2"], r["s1"],
               r["s2"], r["param"], r["dev"], r["vdr"], r["ch"], r["ch2"],
               c_string(r["name"]) if r["name"] is not None else "NULL", i))
    vrows = []
    for typ, nums, six in valid:
        vrows.append("    { %d, { %s }, %s },"
                     % (typ, ", ".join("%d" % v for v in nums),
                        ", ".join("%d" % v for v in six)))
    nrows = "\n".join('    { %s, "%s" },' % (n, n) for n in names)
    words = [u.replace("JOY_EVENT_", "") for u in unnamed]
    unnamed_txt = ", ".join(words[:-1]) + " and " + words[-1]
    return """\
// Generated by tools/gen_scanner_tables.py -- do not edit.
//
// ScannerConfigTable (0x002dc500), ValidJoystickConfigurationTable
// (0x002de558) and EventNameTable (0x002fa2d0), read out of retail's
// SLES_507.31. A scanner row is
//
//     { configurations }, event,
//     scanner, Xor1, Xor2, Shift1, Shift2, Param, AnalogDevice, ValidInReplay,
//     glyph, second glyph, button name
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

// No name for %s,
// nor for the code reader's sixteen.
const EventName EventNameTable[JOY_EVENT_NAMES] = {
%s
};
""" % ("\n".join(out), "\n".join(vrows), unnamed_txt, nrows)


def main():
    events, chars, rows, valid, names, unnamed = read_all()
    outs = [(OUT_H, render_h(events, chars)),
            (OUT_C, render_c(rows, valid, names, unnamed))]
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
