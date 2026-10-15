#!/usr/bin/env python3
r"""Check the debug menu's FRONTB patch (3DS Files/source/debugmenu_patch.c).

Builds the patch for the host, runs it on retail's FRONTB.BUN as the
handheld does at boot, and holds what it wrote against the bundle:

  - every chunk of the Flailer chunk is there, in order and byte for byte,
    but NEW_MAIN_MENU's object count and its bottom filler, cut to a
    separator;
  - NEW_MAIN_MENU has its 31 objects and then the six the port adds: Local
    Wireless's label, mask and filler, shown as MENUITEM_4 and MI_4_MASK
    with the port's LanguageID, then the debug menu's, invisible under
    the hidden names; each row and filler where the rows above put it,
    down to where the filler ended;
  - the two debug screens are last: Be The Cop Setup's objects but the
    six left out (and the debug menu's rows past five), each the same but
    for the texts' rooms, the title's string and the help line's room;
  - bui.c reads the result, and debugmenu_reveal shows the debug menu's
    three once, under MENUITEM_5 and MI_5_MASK, with Local Wireless's
    filler cut to the separator above them.

Usage:
    python tools/debugmenu_check.py [extracted-retail/FRONTEND/FRONTB.BUN]
"""
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hostbuild                                # noqa: E402

SOURCES = ["tools/src/debugmenu_test.c",
           "3DS Files/source/debugmenu_patch.c",
           "3DS Files/source/bui.c",
           "3DS Files/source/bchunk.c"]

FLAILER = 0x80010200
SCREEN = 0x80010201
SCREENDEF = 0x00010203
TEXT = 0x00010212

MAIN_MENU = 0xae0f8aa1
SOURCE = 0xd1eadbca
DEBUG_SCREEN = 0xd98ab71e
DEBUG_RACE = 0xd98d6284
ITEM_HIDDEN = 0xd988c438
MASK_HIDDEN = 0xd98aa6b5
FILL = 0xd986f130
WIRELESS_FILL = 0x3e221977
MENUITEM_2 = 0x52e039f4
MENUITEM_3 = 0x52e039f5
MENUITEM_4 = 0x52e039f6
MENUITEM_5 = 0x52e039f7
MI_2_MASK = 0x708a0bf1
MI_3_MASK = 0x72df3492
MI_4_MASK = 0x75345d33
MI_5_MASK = 0x778985d4
BOTTOM_MASK = 0xaa5d7d3f
PORTLANG_LOCAL_WIRELESS = 2000000
MASK_UNIT = 16.0
SEPARATOR = 0.625
LEFT_OUT = {0x52e039fa, 0x69a2c75e, 0x7e88ffb7, 0xab671c9a, 0x1042eac3,
            0xc67cfb4a}
TITLE = 0x5e9f4683
HELP = 0x75980cf0
# The two screens the port adds, last, with their titles and rows.
DEBUG_SCREENS = [(DEBUG_SCREEN, b"Debug Menu", 5),
                 (DEBUG_RACE, b"Debug Race", 7)]


def left_out(h, rows):
    # A screen with fewer rows than seven loses their labels and values.
    return (h in LEFT_OUT or 0x52e039f2 + rows < h <= 0x52e039f9
            or 0x69a2c756 + rows < h <= 0x69a2c75d)


def rooms(h):
    if 0x52e039f3 <= h <= 0x52e039f9:
        return 24
    if 0x69a2c757 <= h <= 0x69a2c75d:
        return 40
    if h == TITLE:
        return 16
    if h == HELP:
        return 128
    return None


def chunks(buf, off, end):
    out = []
    while off + 8 <= end:
        t, s = struct.unpack_from("<II", buf, off)
        if t == 0 and s == 0:
            off += 8
            continue
        if s > end - off - 8:
            raise SystemExit("chunk overruns at %#x" % off)
        out.append((t, buf[off + 8:off + 8 + s]))
        off += 8 + s
    return out


def flailer(buf):
    for t, p in chunks(buf, 0, len(buf)):
        if t == FLAILER:
            return p
        if t & 0x80000000:
            try:
                return flailer(p)
            except LookupError:
                pass
    raise LookupError("no Flailer chunk")


def u32(p, o):
    return struct.unpack_from("<I", p, o)[0]


def f32(p, o):
    return struct.unpack_from("<f", p, o)[0]


def screen_of(p):
    inner = chunks(p, 0, len(p))
    d = [c for t, c in inner if t == SCREENDEF][0]
    return u32(d, 8), d, [(t, c) for t, c in inner if t != SCREENDEF]


def by_hash(objs, h):
    return [c for t, c in objs if u32(c, 8) == h]


def main():
    bun = Path(sys.argv[1] if len(sys.argv) > 1
               else "extracted-retail/FRONTEND/FRONTB.BUN")
    data = bun.read_bytes()
    bad = []

    def want(ok, what):
        if not ok:
            bad.append(what)

    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, "debugmenu_test")
        one, two = Path(tmp, "patched.bin"), Path(tmp, "revealed.bin")
        r = subprocess.run([str(exe), str(bun), str(one), str(two)],
                           capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stderr)
            sys.exit("debugmenu_test failed")
        print(r.stdout.strip())
        patched, revealed = one.read_bytes(), two.read_bytes()

    orig = chunks(*(lambda p: (p, 0, len(p)))(flailer(data)))
    new = chunks(*(lambda p: (p, 0, len(p)))(flailer(patched)))
    want(len(new) == len(orig) + 2, "two chunks more: %d against %d"
         % (len(new), len(orig)))

    src = None
    for (t0, p0), (t1, p1) in zip(orig, new):
        want(t0 == t1, "chunk type %08x became %08x" % (t0, t1))
        if t0 != SCREEN:
            want(p0 == p1, "chunk %08x differs" % t0)
            continue
        h, d0, o0 = screen_of(p0)
        h1, d1, o1 = screen_of(p1)
        want(h == h1, "screen %08x became %08x" % (h, h1))
        if h == SOURCE:
            src = (d0, o0)
        if h != MAIN_MENU:
            want(p0 == p1, "screen %08x differs" % h)
            continue
        n0, n1 = struct.unpack_from("<H", d0, 28)[0], \
            struct.unpack_from("<H", d1, 28)[0]
        want(n1 == n0 + 6, "main menu count %d against %d" % (n1, n0))
        want(d0[:28] == d1[:28] and d0[30:] == d1[30:],
             "main menu's def differs beyond the count")
        want(len(o1) == len(o0) + 6, "main menu's objects")
        # Its own the same but the biggest BOTTOM_MASK, whose ScaleY alone
        # is now the separator's.
        fills = [c for t, c in o0 if u32(c, 8) == BOTTOM_MASK]
        filler = max(fills, key=lambda c: f32(c, 60))
        cut = None
        for (t0, c0), (t1, c1) in zip(o0, o1):
            if c0 is filler:
                cut = c1
                want(c1[:60] == c0[:60] and c1[64:] == c0[64:]
                     and abs(f32(c1, 60) - SEPARATOR) < 1e-6,
                     "the filler cut to a separator")
            else:
                want(c0 == c1, "main menu's object %08x differs"
                     % u32(c0, 8))
        want(cut is not None, "no filler")
        bottom = f32(filler, 52) + f32(filler, 60) * MASK_UNIT
        added = o1[len(o0):]
        want([u32(c, 8) for t, c in added]
             == [MENUITEM_4, MI_4_MASK, WIRELESS_FILL,
                 ITEM_HIDDEN, MASK_HIDDEN, FILL],
             "added: %s" % ["%08x" % u32(c, 8) for t, c in added])
        want([c[41] for t, c in added] == [1, 1, 1, 0, 0, 0],
             "added objects' visibility %s" % [c[41] for t, c in added])
        item2 = by_hash(o0, MENUITEM_2)[0]
        item3 = by_hash(o0, MENUITEM_3)[0]
        mask2 = by_hash(o0, MI_2_MASK)[0]
        mask3 = by_hash(o0, MI_3_MASK)[0]
        step = f32(item3, 52) - f32(item2, 52)
        mstep = f32(mask3, 52) - f32(mask2, 52)
        # Each row: a copy of MENUITEM_3 a row (or two) below, at
        # MENUITEM_2's X, its room the same; MI_3_MASK as far down; the
        # filler from under the mask to where the filler ended. Past the
        # name (8..40), the visibility (41), X (48), Y (52) and ScaleY
        # (60), every field is the copy's.
        rows = [(1, added[0:3], b"Local Wireless", PORTLANG_LOCAL_WIRELESS,
                 b"MENUITEM_4", b"MI_4_MASK", b"PORT_WIRELESS_FILL"),
                (2, added[3:6], b"Debug Menu", 0, b"MENUITEM_5",
                 b"MI_5_MASK", b"PORT_DEBUG_FILL")]

        def same(a, b, skip):
            # Equal but for the byte ranges in `skip`.
            if len(a) != len(b):
                return False
            for i in range(len(a)):
                if any(lo <= i < hi for lo, hi in skip):
                    continue
                if a[i] != b[i]:
                    return False
            return True

        for row, objs, text, lang, iname, mname, fname in rows:
            (ti, item), (tm, mask), (tf, fill) = objs
            want(ti == TEXT and u32(item, 96) == lang
                 and item[100:].split(b"\0")[0] == text,
                 "row %d's text" % row)
            want(same(item[:96], item3[:96], [(8, 40), (41, 42), (48, 56)])
                 and len(item) == len(item3),
                 "row %d's label is MENUITEM_3's" % row)
            want(item[16:40].split(b"\0")[0] == iname, "row %d's name" % row)
            want(mask[16:40].split(b"\0")[0] == mname,
                 "row %d's mask's name" % row)
            want(fill[16:40].split(b"\0")[0] == fname,
                 "row %d's filler's name" % row)
            want(f32(item, 48) == f32(item2, 48), "row %d's X" % row)
            want(abs(f32(item, 52) - (f32(item3, 52) + step * row)) < 1e-3,
                 "row %d's Y" % row)
            want(same(mask, mask3, [(8, 40), (41, 42), (52, 56)])
                 and abs(f32(mask, 52) - (f32(mask3, 52) + mstep * row))
                 < 1e-3, "row %d's mask is MI_3_MASK's, a row down" % row)
            top = f32(mask, 52) + f32(mask3, 60) * MASK_UNIT
            want(same(fill, filler, [(8, 40), (41, 42), (52, 56), (60, 64)])
                 and abs(f32(fill, 52) - top) < 1e-3
                 and abs(f32(fill, 52) + f32(fill, 60) * MASK_UNIT - bottom)
                 < 1e-3, "row %d's filler" % row)
            print("row %d %s: label y %.0f, mask y %.0f, filler y %.0f "
                  "scale %.4f, to %.0f"
                  % (row, text.decode(), f32(item, 52), f32(mask, 52),
                     f32(fill, 52), f32(fill, 60), bottom))
        print("main menu: %d objects" % n1)

    # The two debug screens, last.
    want(src is not None, "no Be The Cop Setup")
    for (t, p), (name, title, rows) in zip(new[-2:], DEBUG_SCREENS):
        want(t == SCREEN, "no screen at the end")
        h, d, objs = screen_of(p)
        want(h == name, "screen %08x where %08x belongs" % (h, name))
        kept = [(t, c) for t, c in src[1] if not left_out(u32(c, 8), rows)]
        want(struct.unpack_from("<H", d, 28)[0] == len(kept) == len(objs),
             "%08x count %d, %d kept, %d written"
             % (h, struct.unpack_from("<H", d, 28)[0], len(kept), len(objs)))
        want(d[12:28] == src[0][12:28] and d[30:] == src[0][30:],
             "%08x's def differs beyond its name and count" % h)
        for (t0, c0), (t1, c1) in zip(kept, objs):
            h0 = u32(c0, 8)
            room = rooms(h0) if t0 == TEXT else None
            if room is None:
                want(c0 == c1, "object %08x differs" % h0)
                continue
            want(len(c1) == 100 + room and u32(c1, 84) == room,
                 "object %08x's room" % h0)
            want(c1[:84] == c0[:84] and c1[88:96] == c0[88:96],
                 "object %08x's fields" % h0)
            if h0 == TITLE:
                want(c1[100:].split(b"\0")[0] == title
                     and u32(c1, 96) == 0, "the title")
            else:
                want(c1[96:100] == c0[96:100],
                     "object %08x's language" % h0)
        print("%s: %d objects of Be The Cop Setup's %d"
              % (title.decode(), len(objs), len(src[1])))

    # Revealed: the three objects only, and the filler.
    rv = chunks(*(lambda p: (p, 0, len(p)))(flailer(revealed)))
    for (t0, p0), (t1, p1) in zip(new, rv):
        if t0 != SCREEN or screen_of(p0)[0] != MAIN_MENU:
            want(p0 == p1, "reveal touched another chunk")
            continue
        _, _, o0 = screen_of(p0)
        _, _, o1 = screen_of(p1)
        changed = [(a, b) for a, b in zip(o0, o1) if a != b]
        names = sorted("%08x" % u32(b[1], 8) for a, b in changed)
        want(names == sorted(["%08x" % MENUITEM_5, "%08x" % MI_5_MASK,
                              "%08x" % FILL, "%08x" % WIRELESS_FILL]),
             "reveal changed %s" % names)
        for a, b in changed:
            hb = u32(b[1], 8)
            if hb == WIRELESS_FILL:
                want(abs(f32(b[1], 60) - SEPARATOR) < 1e-6
                     and a[1][:60] == b[1][:60] and a[1][64:] == b[1][64:],
                     "the separator")
            else:
                want(b[1][41] == 1 and a[1][:8] == b[1][:8]
                     and a[1][12:41] == b[1][12:41]
                     and a[1][42:] == b[1][42:],
                     "%08x shown, and nothing else" % hb)
    want("reveal 1 0" in r.stdout, "reveal answers")

    for b in bad:
        print("BAD:", b)
    print("debugmenu_check: %s" % ("FAIL" if bad else "ok"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
