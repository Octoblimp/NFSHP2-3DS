#!/usr/bin/env python3
r"""Check the debug menu's FRONTB patch (3DS Files/source/debugmenu_patch.c).

Builds the patch for the host, runs it on retail's FRONTB.BUN as the
handheld does at boot, and holds what it wrote against the bundle:

  - every chunk of the Flailer chunk is there, in order and byte for byte,
    but NEW_MAIN_MENU's object count, its bottom filler, cut to a
    separator, and Options' label and mask, a row down (TASKS 68);
  - NEW_MAIN_MENU has its 31 objects and then the six the port adds: Local
    Wireless's label, mask and filler, shown as MENUITEM_4 and MI_4_MASK
    with the port's LanguageID, in the row Options had, then the debug
    menu's, invisible under the hidden names, a row under Options; each
    filler under its row's mask, down to where the filler ended;
  - the two debug screens are last: Be The Cop Setup's objects but the
    six left out (and the debug menu's rows past five), each the same but
    for the texts' rooms, the title's string and the help line's room;
  - bui.c reads the result, and debugmenu_reveal shows the debug menu's
    three once, under MENUITEM_5 and MI_5_MASK, with the fourth row's
    filler cut to the separator above them;
  - the main menu's order is Hot Pursuit, World Racing, Local Wireless,
    Options, Debug Menu, and with fewer rows held than shown the window
    follows the highlight down and up, round and round: the rows in it in
    their slots, the rest hidden, every mask in it shown but the
    highlighted row's, and the fillers under the slots in use a separator
    each but the last, which runs to the panel's bottom.

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
FILL_4 = 0xca37bd3d
FILL_5 = 0xca37bd3e
MENUITEM_1 = 0x52e039f3
MENUITEM_2 = 0x52e039f4
MENUITEM_3 = 0x52e039f5
MENUITEM_4 = 0x52e039f6
MENUITEM_5 = 0x52e039f7
MI_1_MASK = 0x6e34e350
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
# The main menu's rows, top first, and their masks (TASKS 68).
ORDER = [MENUITEM_1, MENUITEM_2, MENUITEM_4, MENUITEM_3, MENUITEM_5]
MASKS = [MI_1_MASK, MI_2_MASK, MI_4_MASK, MI_3_MASK, MI_5_MASK]
SLOTS = 5


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


def near(a, b):
    return abs(a - b) < 1e-3


def check_scroll(text, slots, want):
    """The harness's walk: each "show" and the objects after it, held
    against the model of debugmenu_patch.c's window. `slots` gives each
    slot's label and mask Y and the fillers' Y and the panel's bottom."""
    labelY, maskY, thinY, fillY, bottom = slots
    blocks = []
    for line in text.splitlines():
        f = line.split()
        if f[0] == "show":
            blocks.append(("show", int(f[1]), int(f[2], 16), int(f[3]), []))
        elif f[0] == "tick":
            blocks.append(("tick", int(f[1]), int(f[2], 16), int(f[3]), []))
        elif f[0] == "held":
            blocks.append(("held", int(f[1]), None, None, []))
        elif f[0] == "obj":
            blocks[-1][4].append((int(f[2], 16), int(f[3]), float(f[4]),
                                  float(f[5])))
    steps = [b for b in blocks if b[0] == "show"]
    ticks = [b for b in blocks if b[0] == "tick"]
    want(len(steps) == 3 * (4 * len(ORDER) + 1) and len(ticks) == len(steps)
         and len(blocks) == 3 + len(steps) + len(ticks),
         "%d blocks" % len(blocks))
    top, i, tops, clamped = 0, -1, {}, 0
    for kind, held, item, got_top, objs in blocks:
        n = min(len(ORDER), held)
        if kind == "tick":
            # The frame after: every label and mask moved off, then the
            # rows laid out again, so the same as the show before it.
            want(item == ORDER[i] and got_top == 2 * len(ORDER),
                 "held %d, row %d: a tick of %08x moved %d"
                 % (held, i, item, got_top))
            where = "held %d, row %d, the tick" % (held, i)
        elif item is None:
            # debugmenu_main_set_slots lays out again, the window clamped,
            # the highlight where it was.
            was = top
            top = max(0, min(top, len(ORDER) - n))
            clamped += top != was
            where = "held %d set, row %d" % (held, i)
        else:
            i = ORDER.index(item) if item in ORDER else -1
            want(i >= 0, "show of %08x" % item)
            if i < top:
                top = i
            elif i >= top + n:
                top = i - n + 1
            want(got_top == top, "held %d, %08x: first row %d, not %d"
                 % (held, item, got_top, top))
            tops.setdefault(held, set()).add(got_top)
            where = "held %d, row %d" % (held, i)
        by = {}
        for h, vis, y, sy in objs:
            by.setdefault(h, []).append((vis, y, sy))
        for j, (lh, mh) in enumerate(zip(ORDER, MASKS)):
            shown = top <= j < top + n
            (lv, ly, _), = by.get(lh, [(None, None, None)])
            (mv, my, _), = by.get(mh, [(None, None, None)])
            want(lv == int(shown), "%s: row %d's label shown %s" % (where, j, lv))
            want(mv == int(shown and j != i),
                 "%s: row %d's mask shown %s" % (where, j, mv))
            if shown:
                want(near(ly, labelY[j - top]) and near(my, maskY[j - top]),
                     "%s: row %d in slot %d at %.1f/%.1f" % (where, j, j - top,
                                                            ly, my))
        # The fillers: retail's two thin separators as they are; under
        # slots 3 to 5, retail's cut filler and the port's two, each a
        # separator under a slot in use but the last, the last to the
        # bottom, none under a slot not in use.
        fills = {2: [], 3: by.get(FILL_4, []), 4: by.get(FILL_5, [])}
        thin = []
        for vis, y, sy in by.get(BOTTOM_MASK, []):
            if near(y, fillY[2]):
                fills[2].append((vis, y, sy))
            else:
                thin.append((vis, y, sy))
        want(sorted(round(y) for v, y, sy in thin) == sorted(round(y)
                                                             for y in thinY)
             and all(v == 1 and near(sy, SEPARATOR) for v, y, sy in thin),
             "%s: the thin separators" % where)
        for s in (2, 3, 4):
            want(len(fills[s]) == 1, "%s: slot %d's filler" % (where, s + 1))
            if len(fills[s]) != 1:
                continue
            vis, y, sy = fills[s][0]
            scale = (SEPARATOR if s < n - 1
                     else (bottom - fillY[s]) / MASK_UNIT)
            want(vis == int(s < n) and near(y, fillY[s])
                 and abs(sy - scale) < 1e-5,
                 "%s: slot %d's filler %d %.1f %.4f against %d %.4f"
                 % (where, s + 1, vis, y, sy, int(s < n), scale))
    want(tops.get(5) == {0} and tops.get(4) == {0, 1}
         and tops.get(3) == {0, 1, 2}, "the windows seen: %s" % tops)
    want(clamped == 2, "the window clamped %d times" % clamped)
    print("scroll: %d steps, first rows %s, the window clamped %d times"
          % (len(steps), {k: sorted(v) for k, v in sorted(tops.items())},
             clamped))


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
        walk = Path(tmp, "scroll.txt")
        r = subprocess.run([str(exe), str(bun), str(one), str(two),
                            str(walk)], capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stderr)
            sys.exit("debugmenu_test failed")
        print(r.stdout.strip())
        patched, revealed = one.read_bytes(), two.read_bytes()
        scroll = walk.read_text()

    orig = chunks(*(lambda p: (p, 0, len(p)))(flailer(data)))
    new = chunks(*(lambda p: (p, 0, len(p)))(flailer(patched)))
    want(len(new) == len(orig) + 2, "two chunks more: %d against %d"
         % (len(new), len(orig)))

    src = None
    slots = None
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
        item1 = by_hash(o0, MENUITEM_1)[0]
        item2 = by_hash(o0, MENUITEM_2)[0]
        item3 = by_hash(o0, MENUITEM_3)[0]
        mask1 = by_hash(o0, MI_1_MASK)[0]
        mask2 = by_hash(o0, MI_2_MASK)[0]
        mask3 = by_hash(o0, MI_3_MASK)[0]
        step = f32(item3, 52) - f32(item2, 52)
        mstep = f32(mask3, 52) - f32(mask2, 52)
        # Its own the same but the biggest BOTTOM_MASK, whose ScaleY alone
        # is now the separator's, and Options' label and mask, whose Y
        # alone is a row down.
        fills = [c for t, c in o0 if u32(c, 8) == BOTTOM_MASK]
        filler = max(fills, key=lambda c: f32(c, 60))
        cut = None
        for (t0, c0), (t1, c1) in zip(o0, o1):
            if c0 is filler:
                cut = c1
                want(c1[:60] == c0[:60] and c1[64:] == c0[64:]
                     and abs(f32(c1, 60) - SEPARATOR) < 1e-6,
                     "the filler cut to a separator")
            elif c0 is item3 or c0 is mask3:
                down = step if c0 is item3 else mstep
                want(c1[:52] == c0[:52] and c1[56:] == c0[56:]
                     and near(f32(c1, 52), f32(c0, 52) + down),
                     "Options' %s a row down"
                     % ("label" if c0 is item3 else "mask"))
            else:
                want(c0 == c1, "main menu's object %08x differs"
                     % u32(c0, 8))
        want(cut is not None, "no filler")
        bottom = f32(filler, 52) + f32(filler, 60) * MASK_UNIT
        added = o1[len(o0):]
        want([u32(c, 8) for t, c in added]
             == [MENUITEM_4, MI_4_MASK, FILL_4,
                 ITEM_HIDDEN, MASK_HIDDEN, FILL_5],
             "added: %s" % ["%08x" % u32(c, 8) for t, c in added])
        want([c[41] for t, c in added] == [1, 1, 1, 0, 0, 0],
             "added objects' visibility %s" % [c[41] for t, c in added])
        # Each row: a copy of MENUITEM_3 (Options) where its row is, at
        # MENUITEM_2's X, its room the same; MI_3_MASK likewise; and the
        # filler under the slot a row (or two) under Options' first,
        # from under that slot's mask to where the filler ended. Past the
        # name (8..40), the visibility (41), X (48), Y (52) and ScaleY
        # (60), every field is the copy's. Local Wireless is in Options'
        # first row, the debug menu's two under it.
        rows = [(0, 1, added[0:3], b"Local Wireless", PORTLANG_LOCAL_WIRELESS,
                 b"MENUITEM_4", b"MI_4_MASK", b"PORT_FILL_4"),
                (2, 2, added[3:6], b"Debug Menu", 0, b"MENUITEM_5",
                 b"MI_5_MASK", b"PORT_FILL_5")]
        for row, under, objs, text, lang, iname, mname, fname in rows:
            (ti, item), (tm, mask), (tf, fill) = objs
            want(ti == TEXT and u32(item, 96) == lang
                 and item[100:].split(b"\0")[0] == text,
                 "%s's text" % text)
            want(same(item[:96], item3[:96], [(8, 40), (41, 42), (48, 56)])
                 and len(item) == len(item3),
                 "%s's label is MENUITEM_3's" % text)
            want(item[16:40].split(b"\0")[0] == iname, "%s's name" % text)
            want(mask[16:40].split(b"\0")[0] == mname,
                 "%s's mask's name" % text)
            want(fill[16:40].split(b"\0")[0] == fname,
                 "%s's filler's name" % text)
            want(f32(item, 48) == f32(item2, 48), "%s's X" % text)
            want(near(f32(item, 52), f32(item3, 52) + step * row),
                 "%s's Y" % text)
            want(same(mask, mask3, [(8, 40), (41, 42), (52, 56)])
                 and near(f32(mask, 52), f32(mask3, 52) + mstep * row),
                 "%s's mask is MI_3_MASK's, in its row" % text)
            top = f32(mask3, 52) + mstep * under + f32(mask3, 60) * MASK_UNIT
            want(same(fill, filler, [(8, 40), (41, 42), (52, 56), (60, 64)])
                 and near(f32(fill, 52), top)
                 and near(f32(fill, 52) + f32(fill, 60) * MASK_UNIT, bottom),
                 "%s's filler" % text)
            print("%s: label y %.0f, mask y %.0f; slot %d's filler y %.0f "
                  "scale %.4f, to %.0f"
                  % (text.decode(), f32(item, 52), f32(mask, 52), under + 3,
                     f32(fill, 52), f32(fill, 60), bottom))
        print("main menu: %d objects" % n1)
        mh = f32(mask3, 60) * MASK_UNIT
        slots = ([f32(item1, 52), f32(item2, 52)]
                 + [f32(item3, 52) + step * k for k in range(3)],
                 [f32(mask1, 52), f32(mask2, 52)]
                 + [f32(mask3, 52) + mstep * k for k in range(3)],
                 [f32(c, 52) for c in fills if c is not filler],
                 {2: f32(filler, 52), 3: f32(mask3, 52) + mstep + mh,
                  4: f32(mask3, 52) + mstep * 2 + mh},
                 bottom)
        want(abs(f32(mask3, 52) + mh - f32(filler, 52)) < 0.05,
             "the filler under Options' mask")

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

    # Revealed: the three objects only, and the filler above them.
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
                              "%08x" % FILL_5, "%08x" % FILL_4]),
             "reveal changed %s" % names)
        for a, b in changed:
            hb = u32(b[1], 8)
            if hb == FILL_4:
                want(abs(f32(b[1], 60) - SEPARATOR) < 1e-6
                     and a[1][:60] == b[1][:60] and a[1][64:] == b[1][64:],
                     "the separator")
            else:
                want(b[1][41] == 1 and a[1][:8] == b[1][:8]
                     and a[1][12:41] == b[1][12:41]
                     and a[1][42:] == b[1][42:],
                     "%08x shown, and nothing else" % hb)
    want("reveal 1 0" in r.stdout, "reveal answers")
    want("rank 0 1 3 2 4 5" in r.stdout, "the main menu's order")

    if slots:
        check_scroll(scroll, slots, want)

    for b in bad:
        print("BAD:", b)
    print("debugmenu_check: %s" % ("FAIL" if bad else "ok"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
