#!/usr/bin/env python3
r"""Check the 3DS C menu system against an independent Python model.

`3DS Files/source/bmenu.c` is the port of FlailerMenu/FlailerMenuItem --
the half of the Flailer UI that is not on disc and had to be decompiled out
of `PS2 Files/NFSHP2.ELF`. The rules it implements are written up in
`docs/formats/flailer-menu.md`, with an address for each.

There is no pre-existing Python reference to diff against the way
texpack/bfont/langtab/bui have one, so this file carries a second
implementation of the same rules, written from the same notes, and runs the
identical event script over it. That does not prove either one matches the
PS2 -- only a picture does that, and for menus the picture is the CIA -- but
it does catch a rule transcribed into C wrongly, which is the failure this
kind of port actually makes.

Usage:
    python tools/bmenu_check.py extracted/FRONTEND/FRONTB.BUN
    python tools/bmenu_check.py extracted/GLOBAL/GLOBALB.BUN
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flailer_dump as fl                       # noqa: E402
import hostbuild                                # noqa: E402
from bhash import bhash                         # noqa: E402

SOURCES = ["tools/src/bmenu_test.c",
           "3DS Files/source/bmenu.c",
           "3DS Files/source/bui.c",
           "3DS Files/source/bchunk.c"]

# FlailerObjectType
TEXT, BITMAP = 1, 2

# ScreenMessage
(SELECT, ACTIVATE, UNACTIVATE, HIGHLIGHT, UNHIGHLIGHT, PAD_LEFT, PAD_RIGHT,
 PAD_UP, PAD_DOWN, SQUARE) = range(1, 11)
SCREEN_START, SCREEN_L1, SCREEN_R1 = 13, 15, 16

# JoyEvent
(SCROLL_UP, SCROLL_DOWN, SCROLL_LEFT, SCROLL_RIGHT, START, SELECT_BTN,
 MENU_SELECT) = 3, 4, 5, 6, 7, 8, 9
MENU_BACK, MENU_L1, MENU_R1, MENU_SQUARE = 11, 13, 15, 17
ANALOG_LEFT, ANALOG_RIGHT, ANALOG_UP, ANALOG_DOWN = 18, 19, 20, 21

# FrontendSoundEvent
SND_UP, SND_DOWN, SND_SELECT = 3, 4, 5

ENABLED, HIGHLIGHTED = 1, 2

# The gp globals' shipped values -- see docs/formats/flailer-menu.md.
HIGHLIGHT_COLOR = 128 | (64 << 8) | (0 << 16)
GRAYED_COLOR = 24 | (24 << 8) | (24 << 16)

HIGHLIGHT_BAR = bhash("HIGHLIGHT_BAR")

SCRIPT = [("down", SCROLL_DOWN), ("down", SCROLL_DOWN), ("down", SCROLL_DOWN),
          ("down", SCROLL_DOWN), ("up", SCROLL_UP), ("left", SCROLL_LEFT),
          ("right", SCROLL_RIGHT), ("select", MENU_SELECT),
          ("square", MENU_SQUARE), ("back", MENU_BACK), ("aup", ANALOG_UP),
          ("adown", ANALOG_DOWN)]


class Menu:
    """FlailerMenu, FlailerMenuItem and the screen-level JoyHandler."""

    def __init__(self, out, screen, first):
        self.out = out                 # the transcript, shared with the C
        self.colors = {}               # object index -> live Color
        self.items = []
        self.bar = -1
        self.current = -1
        self.looping = True
        self.filter_port = -1

        objs = screen["objects"]
        for n in range(16):
            h = bhash("MENUITEM_%d" % n)
            idx = self._find(objs, first, h, TEXT)
            if idx is None:
                continue
            o = objs[idx - first]
            self.items.append(dict(id=n, hash=h, obj=idx, state=ENABLED,
                                   saved=o["color"]))
            self.colors[idx] = o["color"]
        hit = self._find(objs, first, HIGHLIGHT_BAR, BITMAP)
        self.bar = -1 if hit is None else hit
        if self.items:
            self.current = 0

    @staticmethod
    def _find(objs, first, name_hash, want_type):
        for i, o in enumerate(objs):
            if o["name_hash"] != name_hash:
                continue
            if want_type and o["object_type"] != want_type:
                continue
            return first + i
        return None

    # -- callback traffic ------------------------------------------------
    def _send(self, msg, item, port, noise=0, param=0):
        h = self.items[item]["hash"] if 0 <= item < len(self.items) else 0
        self.out.append("msg %d %08x %d %d %d" % (msg, h, port, param, noise))
        return 0                        # the trace callback consumes nothing

    # -- colour ----------------------------------------------------------
    def _recolour(self, item, rgb):
        # SetColor__16FlailerTextChunk keeps the chunk's alpha.
        idx = self.items[item]["obj"]
        cur = self.colors[idx]
        self.colors[idx] = (cur & 0xFF000000) | (rgb & 0x00FFFFFF)

    def _set_state(self, item, bits):
        if bits & HIGHLIGHTED:
            self._recolour(item, HIGHLIGHT_COLOR)
        elif bits & ENABLED:
            self._recolour(item, self.items[item]["saved"])
        self.items[item]["state"] |= bits

    def _clear_state(self, item, bits):
        if bits & ENABLED:
            self._recolour(item, GRAYED_COLOR)
        elif bits & HIGHLIGHTED and self.items[item]["state"] & HIGHLIGHTED:
            self._recolour(item, self.items[item]["saved"])
        self.items[item]["state"] &= ~bits

    def _highlight(self, item, port):
        if not 0 <= item < len(self.items):
            return
        self._set_state(item, HIGHLIGHTED)
        self._send(HIGHLIGHT, item, port)

    def _unhighlight(self, item, port):
        if not 0 <= item < len(self.items):
            return
        self._clear_state(item, HIGHLIGHTED)
        self._send(UNHIGHLIGHT, item, port)

    # -- navigation ------------------------------------------------------
    def _step(self, frm, direction):
        n = len(self.items)
        if n <= 0:
            return -1
        if not self.looping:
            nxt = frm + direction
            return frm if nxt < 0 or nxt >= n else nxt
        cur = frm
        for _ in range(n):
            cur += direction
            if cur >= n:
                cur = 0
            elif cur < 0:
                cur = n - 1
            if cur == frm:
                return frm
            if self.items[cur]["state"] & ENABLED:
                return cur
        return frm

    def _move(self, direction, port):
        nxt = self._step(self.current, direction)
        if nxt == self.current or nxt < 0:
            return
        self._unhighlight(self.current, port)
        self.current = nxt
        self._highlight(self.current, port)

    # -- the public shape ------------------------------------------------
    def activate(self, start):
        if not self.items:
            return
        for i in range(len(self.items)):
            self._send(ACTIVATE, i, self.filter_port)
        self.current = start if 0 <= start < len(self.items) else 0
        if not self.items[self.current]["state"] & ENABLED:
            cur = self.current
            for _ in range(len(self.items)):
                cur = (cur + 1) % len(self.items)
                if cur == self.current:
                    break
                if self.items[cur]["state"] & ENABLED:
                    self.current = cur
                    break
        self._highlight(self.current, self.filter_port)

    def unactivate(self):
        if not self.items:
            return
        self._unhighlight(self.current, self.filter_port)
        for i in range(len(self.items)):
            self._send(UNACTIVATE, i, self.filter_port)

    def close(self):
        # ~FlailerMenuItem: Color = SavedColor, the whole word.
        for it in self.items:
            self.colors[it["obj"]] = it["saved"]

    def _item_joy(self, port, ev):
        table = {SCROLL_LEFT: (PAD_LEFT, 0), ANALOG_LEFT: (PAD_LEFT, 0),
                 SCROLL_RIGHT: (PAD_RIGHT, 0), ANALOG_RIGHT: (PAD_RIGHT, 0),
                 START: (SELECT, SND_SELECT),
                 MENU_SELECT: (SELECT, SND_SELECT),
                 MENU_SQUARE: (SQUARE, 0)}
        if ev not in table:
            return False
        msg, noise = table[ev]
        # FlailerMenuItem's handler puts the event in Param, every case.
        self._send(msg, self.current, port, noise, ev)
        return True

    def _menu_joy(self, port, ev):
        if ev in (SCROLL_UP, ANALOG_UP):
            msg, direction, noise = PAD_UP, -1, SND_UP
        elif ev in (SCROLL_DOWN, ANALOG_DOWN):
            msg, direction, noise = PAD_DOWN, +1, SND_DOWN
        else:
            return self._item_joy(port, ev)
        self._send(msg, self.current, port, noise)
        self._move(direction, port)
        return True

    def joy(self, port, ev, pressed):
        if not pressed:
            return False
        if self.filter_port != -1 and self.filter_port != port:
            return False
        if ev == START:
            self._send(SCREEN_START, self.current, port)
        elif ev in (MENU_L1, MENU_R1):
            self._send(SCREEN_L1 if ev == MENU_L1 else SCREEN_R1,
                       self.current, port)
        return self._menu_joy(port, ev)

    def set_enabled(self, item_id, enabled):
        for i, it in enumerate(self.items):
            if it["id"] != item_id:
                continue
            if enabled:
                self._set_state(i, ENABLED)
            else:
                self._clear_state(i, ENABLED)
            return True
        return False

    def dump(self, label):
        cur = self.items[self.current]["id"] if self.items else -1
        parts = ["step %s %d" % (label, cur)]
        for it in self.items:
            parts.append("%d:%u:%08x" % (it["id"], it["state"],
                                         self.colors[it["obj"]]))
        self.out.append(" ".join(parts))


def run(out, screen, first):
    m = Menu(out, screen, first)
    if not m.items:
        return
    out.append("menu %08x %d %d" % (screen["name_hash"], len(m.items), m.bar))
    for it in m.items:
        out.append("item %d %08x %u %08x"
                   % (it["id"], it["hash"], it["obj"], it["saved"]))

    m.activate(0)
    m.dump("activate")

    for looping in (True, False):
        m.looping = looping
        out.append("mode %s" % ("looping" if looping else "linear"))
        for name, ev in SCRIPT:
            out.append("acted %d" % (1 if m.joy(0, ev, True) else 0))
            m.dump(name)
        out.append("acted %d" % (1 if m.joy(0, SCROLL_DOWN, False) else 0))

    if len(m.items) > 1:
        m.set_enabled(m.items[1]["id"], False)
        m.dump("grayed")
        m.looping = True
        m.activate(0)
        m.dump("reactivate")
        m.joy(0, SCROLL_DOWN, True)
        m.dump("skip")
        m.set_enabled(m.items[1]["id"], True)
        m.dump("ungrayed")

    m.filter_port = 0
    out.append("acted %d" % (1 if m.joy(1, SCROLL_DOWN, True) else 0))
    m.filter_port = -1

    m.unactivate()
    m.dump("unactivate")

    # A menu made again reads the chunk's Color as it was left.
    m.set_enabled(m.items[-1]["id"], False)
    m.dump("leftgray")
    m.close()
    m.dump("close")
    for it in m.items:
        out.append("reopen %d %08x" % (it["id"], m.colors[it["obj"]]))


def py_lines(path):
    data = Path(path).read_bytes()
    found = fl.find_flailers(data)
    if not found:
        return []
    off, size = found[0]
    proj = fl.parse(data, off, size)
    out, first = [], 0
    for s in proj["screens"]:
        run(out, s, first)
        first += len(s["objects"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--max-report", type=int, default=10)
    args = ap.parse_args()

    bad_total = 0
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, "bmenu_test")
        for path in args.files:
            r = subprocess.run([str(exe), str(path)], capture_output=True,
                               text=True)
            if r.returncode:
                sys.stderr.write(r.stderr)
                sys.exit("bmenu_test failed on %s" % path)
            c = [x for x in r.stdout.split(chr(10)) if x.strip()]
            p = py_lines(path)
            bad = [(i, c[i] if i < len(c) else None,
                    p[i] if i < len(p) else None)
                   for i in range(max(len(c), len(p)))
                   if (c[i] if i < len(c) else None)
                   != (p[i] if i < len(p) else None)]
            print("%-34s %d lines, %d differ"
                  % (Path(path).name, len(p), len(bad)))
            for i, cv, pv in bad[:args.max_report]:
                print("  [%d] C=%r" % (i, cv))
                print("      py=%r" % (pv,))
            if len(bad) > args.max_report:
                print("  ... and %d more" % (len(bad) - args.max_report))
            bad_total += len(bad)
    return 1 if bad_total else 0


if __name__ == "__main__":
    sys.exit(main())
