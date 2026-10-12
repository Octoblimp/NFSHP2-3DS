#!/usr/bin/env python3
"""Cross-check 3DS Files/source/songmon.c, the EA TRAX box, against the
retail image, SLES_507.31.

**The model** is retail's own tNewSongMonitor -- the constructor
(0x0016bd30) and Update (0x0016be20) -- run in retail_model.RetailEmu on a
monitor of its own, with the real bStringHash and bSPrintf. The harness
(tools/src/songmon_test.c) runs songmon.c's.

**The stubs** print what they are asked, on both sides: sound::jukebox's
IsPlaying and GetCurrentTrack, GetTrackName / GetTrackArtist /
GetTrackLabel, FlailerSetScreenVisibility (printed as the port's bool, 1
shown), FlailerPrintf (its format done here, bVSPrintf's "(null)" for a
NULL string), FlailerGetWidth, FlailerGetScale and FlailerSetScaleX. The
objects they answer for are the script's: text with a fixed width, bitmaps
whose width is (int)(texture width * scale X), as CalculateWidth's is, and
objects that are not there. RealTimer is gp-19608, written by the script.

**The script** starts silent, then plays tunes through the five seconds:
the first frame (t is 0, hidden), inside, exactly 5 and past it, a timer
behind the start, a wrap, a start at RealTimer 0 and at 0x7fffffff, the
jukebox going quiet and starting the same tune again, each of the four
lines the widest (and ties, and a negative one), NULL and empty fields,
and strips that are missing, scaled negative or rescaled by the last pass.

    python tools/songmon_check.py
    python tools/songmon_check.py --mutate [--only a,b]
    python tools/songmon_check.py --dump out/songmon
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/songmon_test.c"
SONGMON = "3DS Files/source/songmon.c"
SOURCES = [HARNESS, SONGMON]
HARNESS_TIMEOUT = 30

GP = retail_model.RETAIL_GP
TIMER = GP - 19608              # RealTimer
TITLEW = GP - 21244             # RECORD_TITLE's width

F_CTOR = 0x0016bd30
F_UPDATE = 0x0016be20
S_ISPLAYING = 0x001aecb0
S_CURRENT = 0x001af040
S_TRACK = {0x001aee90: 1, 0x001aeee0: 0, 0x001aef30: 2}  # name, artist, label
S_VIS = 0x0016eb68
S_PRINTF = 0x00143e70
S_WIDTH = 0x00144190
S_GETSCALE = 0x001444e8
S_SETX = 0x00144530


def fbits(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


def bitsf(u):
    return struct.unpack("<f", struct.pack("<I", u & M32))[0]


def f32(v):
    return bitsf(fbits(v))


def bhash(s):
    h = 0xffffffff
    for c in s.encode("latin-1"):
        h = (h * 33 + c) & M32
    return h


# ================================================================== script

LINES = ("RECORD_LABEL", "ARTIST_NAME", "SONG_TITLE", "RECORD_TITLE")
STRIPS = ["CHYRON_BG_%d" % i for i in range(1, 6)]
SX = fbits(17.8)


def objects(widths, strips=None):
    """The four lines' widths, and the strips (texture width, sx, sy)."""
    out = ["text|%s|%d" % (n, w) for n, w in zip(LINES, widths)]
    for name, st in zip(STRIPS, strips or [(16, SX, fbits(5.62))] +
                        [(16, SX, fbits(1.25))] * 4):
        out.append("bitmap|%s|%d|%#x|%#x" % ((name,) + st))
    return out


def tune(n, label, artist, name):
    return ["track|%#x" % n, "field|2|%s" % label, "field|0|%s" % artist,
            "field|1|%s" % name]


def script():
    s = []
    # Nothing yet: no start, so nothing but the question.
    s += ["update", "dump", "timer|500", "update", "dump"]
    s += objects((120, 140, 170, 130))
    s += tune(5, "^", "Hot Action Cop", "Fever for the Flava")
    # The tune starts at 1000: its first frame is t = 0, hidden.
    s += ["playing|1", "timer|1000", "update", "dump"]
    s += ["timer|1001", "update", "dump"]            # shown, printed
    s += ["timer|5000", "update", "update", "dump"]   # shown, not again
    s += ["timer|20999", "update", "dump"]           # 4.99975 s
    s += ["timer|21000", "update", "dump"]           # 5 s: hidden
    s += ["timer|90000", "update", "dump"]
    s += ["timer|999", "update", "dump"]             # behind the start
    s += ["timer|1000", "update"]
    # The jukebox goes quiet, and the same tune starts again: a new start.
    s += ["playing|0", "timer|3000", "update", "dump"]
    s += ["timer|3001", "update", "dump"]
    s += ["playing|1", "timer|4000", "update", "dump"]
    s += ["timer|4400", "update", "dump"]
    # A new tune while shown; the artist is the widest.
    s += tune(0x10003, "Superkala", "Course of Nature With A Long Name",
              "Wall Of Shame")
    s += objects((90, 260, 200, 130))
    s += ["timer|6000", "update", "dump", "timer|6004", "update", "dump"]
    # The label widest, then RECORD_TITLE, then a tie, then negatives.
    for widths in ((300, 20, 40, 130), (10, 20, 40, 130), (77, 77, 77, 77),
                   (10, 131, 40, 130), (10, 5, 3, -9),
                   (-5, -40, -3, -9), (0, 0, 0, 0), (16777217, 3, 2, 1),
                   (2147483600, 5, 5, 5)):
        s += objects(widths)
        s += ["track|%#x" % (len(s) & 0xffff), "timer|8000", "update",
              "timer|8400", "update", "dump"]
    # NULL fields, and the strips scaled the last pass left them.
    s += tune(0x40, "~", "~", "~")
    s += objects((100, 101, 102, 103), [(16, SX, SX)] * 5)
    s += ["timer|10000", "update", "timer|10400", "update", "dump"]
    s += ["track|0x41", "timer|11000", "update", "timer|11400", "update",
          "dump"]
    # Strips that are missing, scaled negative, 0 wide, or odd.
    s += objects((100, 101, 102, 103),
                 [(16, fbits(-2.0), fbits(1.0)), (0, fbits(3.0), 0),
                  (7, fbits(0.3), fbits(9.5)), (1000, fbits(1e-3), 0),
                  (16, SX, 0)])
    s += ["gone|CHYRON_BG_5"]
    s += ["track|0x42", "timer|12000", "update", "timer|12400", "update",
          "dump"]
    # (Fresh strips: that pass left two at an infinite scale.)
    s += objects((100, 101, 102, 103))
    s += ["gone|SONG_TITLE", "gone|RECORD_TITLE"]
    s += ["track|0x43", "timer|13000", "update", "timer|13400", "update",
          "dump"]
    # A timer that wraps under the start.
    s += objects((100, 101, 102, 103))
    s += ["track|0x44", "timer|0xffffff00", "update", "timer|0x100",
          "update", "dump", "timer|0x4d00", "update", "dump",
          "timer|0x4e00", "update", "dump"]
    # A start at RealTimer 0, and at 0x7fffffff: never shown.
    s += ["track|0x45", "timer|0", "update", "timer|400", "update", "dump"]
    s += ["track|0x46", "timer|0x7fffffff", "update", "timer|0x80000100",
          "update", "dump"]
    s += ["track|0x47", "timer|0x80000000", "update",
          "timer|0x80000400", "update", "dump"]
    # Quiet: the old start still runs out.
    s += ["playing|0", "timer|0x80004000", "update", "dump",
          "timer|0x80008000", "update", "dump"]
    s += ["playing|1", "track|0x47", "timer|0x80009000", "update",
          "timer|0x80009001", "update", "dump"]
    return s


# =================================================================== model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.playing = 0
        self.track = 0
        self.fields = [None, None, None]
        self.objs = {}
        self.strs = [e.alloc(128) for _ in range(3)]
        self.mon = e.alloc(32)
        e.write(self.mon, b"\0" * 32)
        e.put32(TIMER, 0)
        e.stub(S_ISPLAYING, self.is_playing)
        e.stub(S_CURRENT, self.current)
        for a, field in S_TRACK.items():
            e.stub(a, self.track_stub(field))
        e.stub(S_VIS, self.vis)
        e.stub(S_PRINTF, self.printf)
        e.stub(S_WIDTH, self.width)
        e.stub(S_GETSCALE, self.get_scale)
        e.stub(S_SETX, self.set_x)
        e.call(F_CTOR, self.mon, limit=10000)

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a, n=400):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    # ---- stubs

    def is_playing(self, em):
        self.emit("  isplaying")
        return self.playing

    def current(self, em):
        self.emit("  current")
        return self.track

    def track_stub(self, field):
        def stub(em):
            if s32(em.reg[4]) != -1 or s32(em.reg[5]) != -1:
                self.emit("  track asked for %d %d" % (
                    s32(em.reg[4]), s32(em.reg[5])))
            self.emit("  track %d" % field)
            v = self.fields[field]
            if v is None:
                return 0
            self.e.write(self.strs[field], v.encode("latin-1") + b"\0")
            return self.strs[field]
        return stub

    def vis(self, em):
        r = em.reg
        self.emit("  vis %08x %d" % (r[4] & M32, 1 if (r[5] & M32) == 0
                                      else 0))
        return 0

    def printf(self, em):
        r = em.reg
        fmt = self.cstr(r[6] & M32)
        a = r[7] & M32
        s = self.cstr(a) if a else "(null)"
        self.emit("  print %08x %08x %s" % (r[4] & M32, r[5] & M32,
                                            fmt.replace("%s", s)))
        return 0

    def find(self, h):
        o = self.objs.get(h)
        return o if o and o["kind"] else None

    def width(self, em):
        r = em.reg
        o = self.find(r[5] & M32)
        w = 0
        if o and o["kind"] == 1:
            w = o["width"]
        elif o and o["kind"] == 2:
            w = int(f32(float(o["texw"]) * bitsf(o["sx"])))
        self.emit("  width %08x %08x %d" % (r[4] & M32, r[5] & M32, w))
        return w & M32

    def get_scale(self, em):
        r = em.reg
        o = self.find(r[5] & M32)
        self.emit("  scale %08x %08x" % (r[4] & M32, r[5] & M32))
        if o:
            self.e.put32(r[6] & M32, o["sx"])
            self.e.put32(r[7] & M32, o["sy"])
        return 0

    def set_x(self, em):
        r = em.reg
        sx = em.fpr[12] & M32
        o = self.find(r[5] & M32)
        self.emit("  setx %08x %08x %08x" % (r[4] & M32, r[5] & M32, sx))
        if o:
            o["sx"] = sx
        return 0

    # ---- ops

    def slot(self, name):
        h = bhash(name)
        if h not in self.objs:
            self.objs[h] = {"kind": 0, "width": 0, "texw": 0,
                            "sx": 0, "sy": 0}
            self.order.append(h)
        return self.objs[h]

    def op(self, a):
        e = self.e
        o = a[0]
        if o == "playing":
            self.playing = int(a[1], 0)
        elif o == "track":
            self.track = int(a[1], 0) & M32
        elif o == "field":
            t = a[2]
            self.fields[int(a[1], 0)] = (None if t == "~" else
                                         "" if t == "^" else t)
        elif o == "timer":
            e.put32(TIMER, int(a[1], 0) & M32)
        elif o == "text":
            ob = self.slot(a[1])
            ob.update(kind=1, width=int(a[2], 0), sx=fbits(1.0),
                      sy=fbits(1.0))
        elif o == "bitmap":
            ob = self.slot(a[1])
            ob.update(kind=2, texw=int(a[2], 0), sx=int(a[3], 0) & M32,
                      sy=int(a[4], 0) & M32)
        elif o == "gone":
            self.slot(a[1])["kind"] = 0
        elif o == "update":
            e.call(F_UPDATE, self.mon, limit=200000)
        elif o == "dump":
            g = e.u32
            m = self.mon
            self.emit("  mon %08x %08x %08x %d %d %d" % (
                g(m), g(m + 4), g(m + 8), s32(g(m + 12)), s32(g(m + 16)),
                s32(g(TITLEW))))
            for h in self.order:
                ob = self.objs[h]
                self.emit("  obj %08x %d %08x" % (h, ob["kind"], ob["sx"]))
        else:
            raise ValueError(o)

    def run(self, lines):
        self.order = []
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            self.op(line.split("|"))
            e.reg[29] = sp
        return self.out


def model(lines):
    return Model().run(lines)


# ================================================================= build

def build_harness(tmp, name="songmon_test"):
    # The port keeps the box up 8 s; retail's 5 is what the model runs.
    return hostbuild.build(tmp, SOURCES, name=name,
                           flags=hostbuild.FLAGS
                           + ["-DCHYRON_SECONDS=5.0f"])


def run_harness(exe, sc_path, out_path):
    try:
        with open(out_path, "w") as fh:
            r = subprocess.run([str(exe), str(sc_path)], stdout=fh,
                               stderr=subprocess.PIPE, text=True,
                               timeout=HARNESS_TIMEOUT)
    except subprocess.TimeoutExpired:
        print("harness hung, killed after %d s" % HARNESS_TIMEOUT)
        return pcc.HARNESS_HUNG
    if r.returncode != 0:
        print("harness exited %d" % r.returncode)
        if r.stderr:
            print(r.stderr[:2000])
    return r.returncode


diff = pcc.diff


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return sc


# ============================================================= mutations

S = SONGMON
MUTATIONS = [
    ("init-track", S, "    m->track = 0xffffffffu;", "    m->track = 0;"),
    ("init-start", S, "    m->track = 0xffffffffu;" + NL
     + "    m->start = NO_START;",
     "    m->track = 0xffffffffu;" + NL + "    m->start = 0;"),
    ("init-screen", S, 'bchunk_hash("CHYRON")', 'bchunk_hash("CHYRONS")'),
    ("no-start-value", S, "#define NO_START 0x7fffffffu",
     "#define NO_START 0x7ffffffeu"),
    ("quiet-keeps", S, "        m->starts = 0;", "        (void)0;"),
    ("quiet-start", S, "        m->starts = 0;",
     "        m->starts = 0;" + NL + "        m->start = NO_START;"),
    ("same-track", S, "track != m->track || m->starts == 0",
     "track != m->track"),
    ("starts-only", S, "track != m->track || m->starts == 0",
     "m->starts == 0"),
    ("keep-track", S, "            m->track = track;", "            (void)0;"),
    ("start-stale", S, "            m->start = H->realTimer(H->user);",
     "            m->start = H->realTimer(H->user) + 1;"),
    ("starts-set", S, "            m->starts++;", "            m->starts = 1;"),
    ("printed-kept", S, "            m->printed = 0;", "            (void)0;"),
    ("zero-start-shows", S, "m->start == 0 || m->start == NO_START",
     "m->start == NO_START"),
    ("none-start-shows", S, "m->start == 0 || m->start == NO_START",
     "m->start == 0"),
    ("t-unsigned", S, "(float)(int32_t)(H->realTimer(H->user) - m->start)",
     "(float)(H->realTimer(H->user) - m->start)"),
    ("t-rate", S, "m->start) * 0.00025f;", "m->start) * 0.00026f;"),
    ("t-zero-shows", S, "!(0.0f < t) || !(t < CHYRON_SECONDS)",
     "!(0.0f <= t) || !(t < CHYRON_SECONDS)"),
    ("t-five-shows", S, "!(0.0f < t) || !(t < CHYRON_SECONDS)",
     "!(0.0f < t) || !(t <= CHYRON_SECONDS)"),
    ("t-four", S, "!(0.0f < t) || !(t < CHYRON_SECONDS)",
     "!(0.0f < t) || !(t < CHYRON_SECONDS - 0.1f)"),
    ("hide-vis", S, "        H->setScreenVisible(H->user, m->screen, 0);",
     "        H->setScreenVisible(H->user, m->screen, 1);"),
    ("hide-silent", S, "        H->setScreenVisible(H->user, m->screen, 0);"
     + NL + "        return;", "        return;"),
    ("hide-falls", S, "        H->setScreenVisible(H->user, m->screen, 0);"
     + NL + "        return;",
     "        H->setScreenVisible(H->user, m->screen, 0);"),
    ("show-silent", S, "    if (SHOW_CHYRON) {" + NL
     + "        H->setScreenVisible(H->user, m->screen, 1);",
     "    if (0) {" + NL
     + "        H->setScreenVisible(H->user, m->screen, 1);"),
    ("show-after", S, "    if (!m->printed) {" + NL + "        print_tune(m);"
     + NL + "    }", "    if (!m->printed) {" + NL + "        print_tune(m);"
     + NL + "        H->setScreenVisible(H->user, m->screen, 1);" + NL
     + "    }"),
    ("print-always", S, "    if (!m->printed) {", "    if (1) {"),
    ("printed-unset", S, "    m->printed = 1;", "    (void)0;"),
    ("null-text", S, 's ? s : "(null)"', 's ? s : ""'),
    ("label-field", S, "H->track(H->user, JB_TRACK_LABEL)",
     "H->track(H->user, JB_TRACK_GENRE)"),
    ("name-field", S, "H->track(H->user, JB_TRACK_NAME)",
     "H->track(H->user, JB_TRACK_ARTIST)"),
    ("order-ask", S, "    const char* name = H->track(H->user, JB_TRACK_NAME);"
     + NL + "    const char* artist = H->track(H->user, JB_TRACK_ARTIST);",
     "    const char* artist = H->track(H->user, JB_TRACK_ARTIST);" + NL
     + "    const char* name = H->track(H->user, JB_TRACK_NAME);"),
    ("label-object", S, 'print_line(m, "RECORD_LABEL", "%s", label);',
     'print_line(m, "RECORD_TITLE", "%s", label);'),
    ("title-quotes", S, 'print_line(m, "SONG_TITLE", "\\"%s\\"", name);',
     'print_line(m, "SONG_TITLE", "%s", name);'),
    ("print-order", S, '    print_line(m, "RECORD_LABEL", "%s", label);' + NL
     + '    print_line(m, "ARTIST_NAME", "%s", artist);',
     '    print_line(m, "ARTIST_NAME", "%s", artist);' + NL
     + '    print_line(m, "RECORD_LABEL", "%s", label);'),
    ("title-width-last", S, '    m->titleWidth = width_of(m, "RECORD_TITLE");'
     + NL + '    int32_t widest = width_of(m, "RECORD_LABEL");',
     '    int32_t widest = width_of(m, "RECORD_LABEL");' + NL
     + '    m->titleWidth = width_of(m, "RECORD_TITLE");'),
    ("widest-artist", S, "    if (widest < w) {" + NL + "        widest = w;"
     + NL + "    }" + NL + "    w = width_of", "    if (0) {" + NL
     + "        widest = w;" + NL + "    }" + NL + "    w = width_of"),
    ("widest-title", S, '    w = width_of(m, "SONG_TITLE");' + NL
     + "    if (widest < w) {", '    w = width_of(m, "SONG_TITLE");' + NL
     + "    if (0) {"),
    ("widest-record", S, "    if (widest < m->titleWidth) {",
     "    if (0) {"),
    ("widest-le", S, "    if (widest < m->titleWidth) {",
     "    if (widest <= m->titleWidth + 1) {"),
    ("widest-unsigned", S, "    if (widest < m->titleWidth) {",
     "    if ((uint32_t)widest < (uint32_t)m->titleWidth) {"),
    ("strips-from-0", S, "    for (int i = 1; i <= 5; i++) {",
     "    for (int i = 0; i < 5; i++) {"),
    ("strips-4", S, "    for (int i = 1; i <= 5; i++) {",
     "    for (int i = 1; i < 5; i++) {"),
    ("strip-name", S, '"CHYRON_BG_%d"', '"CHYRON_BG%d"'),
    ("scale-preset", S, "        float sx = 1.0f, sy = 1.0f;",
     "        float sx = 0.5f, sy = 1.0f;"),
    ("scale-undivided", S, "        texW = texW / sx;", "        (void)sx;"),
    ("pad-20", S, "((float)widest + 20.0f)", "((float)widest + 18.0f)"),
    ("pad-after", S, "((float)widest + 20.0f) / texW",
     "(float)widest / texW + 20.0f"),
    ("setx-skip", S, "        H->setScaleX(H->user, m->screen, hash, scale);",
     "        (void)scale;"),
    ("setx-double", S, "((float)widest + 20.0f) / texW",
     "(float)(((double)widest + 20.0) / (double)texW)"),
]

EQUIVALENT = {
    "t-unsigned": "t is only asked whether it is inside (0, 5): a difference "
                  "of 2^31 or more is outside either way, negative signed "
                  "and past 500,000 s unsigned",
    "scale-preset": "FlailerGetScale leaves the pair alone only for an "
                    "object that is not there, and FlailerGetWidth gives 0 "
                    "for the same object: 0 over any positive preset is 0",
}


def mutate_pass(only=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    lines = script()
    base = model(lines)
    caught, survived, missing, equivalent = 0, [], [], []
    indir = tempfile.TemporaryDirectory()
    scp = write_script(indir.name, lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        run_harness(exe, scp, out)
        if diff(base, out.read_text().splitlines(), quiet=True):
            print("base already differs -- fix that before mutating")
            return 1

    for m in todo:
        name, rel, before, after = m
        path = ROOT / rel
        text = path.read_text(encoding="utf-8", newline="")
        crlf = "\r\n" in text
        probe = before.replace(NL, "\r\n") if crlf else before
        repl = after.replace(NL, "\r\n") if crlf else after
        if text.count(probe) != 1:
            missing.append(name)
            print("  %-44s PATTERN %s" % (
                name, "NOT FOUND" if not text.count(probe) else "NOT UNIQUE"))
            continue
        new = text.replace(probe, repl, 1)
        try:
            hostbuild.write_source(path, new)
            with tempfile.TemporaryDirectory() as tmp:
                try:
                    exe = build_harness(tmp)
                except SystemExit:
                    print("  %-44s did not compile (caught)" % name)
                    caught += 1
                    continue
                out = Path(tmp) / "m.txt"
                rc = run_harness(exe, scp, out)
                if rc == pcc.HARNESS_HUNG:
                    print("  %-44s hung the harness (caught)" % name)
                    caught += 1
                    continue
                if rc != 0:
                    print("  %-44s crashed the harness (caught)" % name)
                    caught += 1
                    continue
                n = diff(base, out.read_text().splitlines(), quiet=True)
                if n:
                    print("  %-44s caught, %d lines" % (name, n))
                    caught += 1
                elif name in EQUIVALENT:
                    print("  %-44s survived, equivalent by construction"
                          % name)
                    equivalent.append(name)
                else:
                    print("  %-44s SURVIVED" % name)
                    survived.append(name)
        finally:
            try:
                hostbuild.write_source(path, text)
            except OSError:
                sys.exit("could not restore %s -- it still holds the "
                         "mutation %s. Put the original line back before "
                         "trusting anything printed above." % (rel, name))
    indir.cleanup()

    real = [m for m in todo if m[0] not in missing]
    holes = [s for s in survived if s not in EQUIVALENT]
    ran = {m[0] for m in todo}
    stale = [n for n in EQUIVALENT
             if n not in equivalent and n not in missing
             and (n in ran or only is None)]
    if missing:
        print("%d PATTERN NOT FOUND -- the tally above is over %d of %d"
              % (len(missing), len(real), len(todo)))
    print("%d mutations, %d caught, %d equivalent, %d unexplained"
          % (len(real), caught, len(equivalent), len(holes)))
    for name in holes:
        print("  unexplained: %s" % name)
    for name in stale:
        print("  listed as equivalent but %s: %s"
              % ("caught" if name in ran else "names no mutation", name))
    return 1 if (holes or missing or stale) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None))

    lines = script()
    got = model(lines)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = write_script(tmp, lines)
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text().splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(got) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(got, harness)
    print("%d ops, %d lines, %d differ" % (len(lines), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
