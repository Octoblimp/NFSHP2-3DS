#!/usr/bin/env python3
"""Cross-check 3DS Files/source/raceovermsg.c and flailerwrap.c, the
race-over overlay's message, against the retail image, SLES_507.31.

**The model** is retail's own code run in retail_model.RetailEmu:
Player::FillInRaceOverMessages (0x00181558),
FormatFinishPositionForRaceOverOverlay (0x00181498),
FormatTimeForRaceOverOverlay (0x00181500) and RenderTextIntoGroup
(0x00144ba0), with everything under them -- RacingCar's GetBestLapTime and
GetPlayer, Timer::PrintToString(char *, float, int) with RoundSeconds,
SetTime and PrintToString(char *, int), WriteTextIntoChunk, isspace,
bSPrintf and bStrLen.

**The stubs** print what they are asked, on both sides:
GetTranslatedString(int), UseTheRaceEvent, MaybeDoKnockoutRaceOverSpeech,
FindFlailerObjectByGroup, FlailerObjectChunk::SetVisibility,
FlailerTextChunk::SetString and GetScaledHeight. The harness
(tools/src/raceover_test.c) runs raceovermsg.c and flailerwrap.c with
timer.c and bprintf.c.

Where retail has no message it renders its stack's leftovers. The model
zeroes the stack below its frame before each call, so those read as the
port's empty message.

**The script** wraps texts into groups of every shape; prints every place
and times in each language; and fills the message over every RaceType,
FinishReason, place, knockout size, race event, You're The Cop with one and
two players, and random cases.

    python tools/raceover_check.py
    python tools/raceover_check.py --mutate [--only a,b]
    python tools/raceover_check.py --dump out/raceover
"""
import argparse
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import language_dump                    # noqa: E402
import mutpar                           # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402
from mipsemu import M32, s32            # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/raceover_test.c"
RO = "3DS Files/source/raceovermsg.c"
FW = "3DS Files/source/flailerwrap.c"
TIMER = "3DS Files/source/timer.c"
SOURCES = [HARNESS, RO, FW, TIMER, "3DS Files/source/bprintf.c"]
HARNESS_TIMEOUT = 60
ENGLISH = ROOT / "extracted-retail" / "LANGUAGES" / "FE_ENGLISH.BIN"

GP = retail_model.RETAIL_GP
RP = 0x0031a898
RACE_EVENT = 0x0031b600
LANGUAGE = 0x0031c1c8
P_CUR_RACE = GP - 22272
BY_NUMBER = GP - 20936

F_FILL, F_FPOS, F_FTIME, F_RTIG = 0x00181558, 0x00181498, 0x00181500, \
    0x00144ba0
S_TR, S_USETRE, S_KOSPEECH = 0x0021e560, 0x001841a8, 0x00207018
S_FIND, S_VIS, S_SETSTR, S_HEIGHT = 0x00143dd8, 0x00140728, 0x00140e20, \
    0x00140cd8

MAX_RC = MAX_CARS = MAX_PLAYERS = 4
PLAYER_SIZE, CAR_SIZE, RC_SIZE, RACE_SIZE = 2752, 64, 192, 1700

# The overlay's ids, the places' words and the race type's names.
MSG_IDS = list(range(59010, 59021)) + list(range(59022, 59028))
PLACE_IDS = [321001, 61009] + list(range(321003, 321010))
GROUP = 0xc707e093
HUD = 0x52f0ac10


def fb(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


# ================================================================== script

def english():
    """The overlay's English strings, as `str` ops."""
    t = language_dump.LanguageTable(ENGLISH.read_bytes(), ENGLISH)
    s = []
    for i in MSG_IDS + PLACE_IDS:
        text = t.by_id.get(i)
        if text:
            s.append("str|%d|%s" % (i, text))
    return s


def wrap_cases(rnd):
    """RenderTextIntoGroup over groups and texts of every shape."""
    s = ["grp|1|10|%#x|20|20|20" % fb(100.0),
         "grp|1|11|%#x|8|12|5|30" % fb(-3.5),
         "grp|1|12|%#x|3" % fb(0.0),
         "grp|2|10|%#x|2|2|2|2|2|2" % fb(7.75),
         "grp|1|13|%#x|%s" % (fb(12.0), "|".join(["16"] * 34)),
         "height|%#x" % fb(18.5)]
    texts = ["", "short", "a b c", "@", "a@b@c", "@ @", "x" * 40,
             "You finished in 1st place!", "one two three four five six",
             "You were arrested!@You didn't record a lap time.",
             "tab\tseparated\twords here", "  leading", "trailing  ",
             "@@@@", "a" * 17, "a" * 18 + " b", "a" * 19 + " b",
             "abcdefghijklmnopq rstu", "w " * 30]
    for g in (10, 11, 12, 13):
        for txt in texts:
            s.append("rtig|1|%d|%s" % (g, txt))
    for txt in texts[:6]:
        s += ["rtig|2|10|%s" % txt, "rtig|3|10|%s" % txt]
    for h in (0.0, -40.25, 1e9, 3.9):
        s += ["height|%#x" % fb(h), "rtig|1|11|a b c d e f g h",
              "rtig|1|10|x"]
    s.append("height|%#x" % fb(18.5))
    for _ in range(300):
        g = rnd.choice((10, 11, 12, 13))
        n = rnd.randrange(0, 70)
        txt = "".join(rnd.choice("ab  @\tcd") for _ in range(n))
        s.append("rtig|1|%d|%s" % (g, txt))
    return s


def fill(rtype, np, cop, use, etype, ncars, place, reason, num=0,
         other=0, own=1, best=(0, 0, 0, 0, 0), rtime=0, finish=0):
    """A fill of player 0's message. `num` is the PlayerNumber GetPlayer's
    player has; `own` 0 points the RacingCar at no car; `other` is the other
    player's FinishReason."""
    s = ["rp|%d|%d|%d" % (rtype, np, cop), "ev|%d|%d" % (use, etype),
         "race|%d|%d" % (ncars, finish),
         "rc|0|%d|%d|%d|%s" % (place, reason, rtime & M32,
                               "|".join(str(b & M32) for b in best)),
         "rc|1|2|%d|0|0|0|0|0|0" % other,
         "player|0|%d|%#x|0" % (num, HUD), "player|1|%d|%#x|1" % (1 - num, HUD),
         "car|0|0", "car|1|1", "link|0|%d" % (0 if own else -1),
         "bynum|%d|0" % (num & 1), "bynum|%d|1" % (1 - (num & 1))]
    if num not in (0, 1):
        s += ["bynum|0|0", "bynum|1|1"]
    return s + ["fill|0"]


def fill_cases(rnd):
    s = ["grp|%#x|%#x|%#x|24|24|24" % (HUD, GROUP, fb(200.0))]
    best = (0, 0, 0, 0, 0)
    laps = (400000, 0x7fffffff, 0, 239999, 1)
    # Every RaceType and FinishReason, outside You're The Cop.
    for rtype in range(0, 7):
        for reason in range(0, 6):
            for place in (1, 3, 8, 0):
                s += fill(rtype, 1, 0, 0, 0, 8, place, reason,
                          best=laps, rtime=1234567)
    # Time trial: each boundary's best lap, set and unset.
    for finish in range(5):
        for reason in (1, 2):
            s += fill(2, 1, 0, 0, 0, 1, 1, reason, best=laps,
                      finish=finish)
    # Race knockout: the place against the number of cars.
    for ncars in (1, 2, 3, 4, 8):
        for place in range(0, 9):
            for reason in (0, 1, 3):
                s += fill(4, 1, 0, 0, 0, ncars, place, reason)
    # Lap knockout, every place.
    for place in range(0, 9):
        for reason in (1, 2, 3):
            s += fill(3, 1, 0, 0, 0, 8, place, reason)
    # A race event: point to point and the rest.
    for rtype in (1, 5):
        for use in (0, 1):
            for etype in (0, 4, 5, 6):
                for reason in range(0, 6):
                    s += fill(rtype, 1, 0, use, etype, 8, 2, reason,
                              rtime=(723456, 4001, 0, 0x7fffffff,
                                     14400000)[reason % 5])
    # You're The Cop.
    for rtype in (1, 5):
        for np in (0, 1, 2, 3):
            for reason in range(0, 6):
                for num in (0, 1, 2):
                    for other in (0, 4, 5):
                        s += fill(rtype, np, 1, 0, 0, 2, 1, reason, num,
                                  other)
                s += fill(rtype, np, 1, 0, 0, 2, 1, reason, own=0)
    # The cop flag beside the other races.
    for rtype in (2, 3, 4):
        s += fill(rtype, 2, 1, 1, 5, 4, 2, 1, best=laps)
    # Every language's time.
    for lang in range(6):
        s += ["lang|%d" % lang]
        s += fill(2, 1, 0, 0, 0, 1, 1, 1, best=(4321098,) * 5)
        s += fill(1, 1, 0, 1, 5, 8, 1, 1, rtime=99999)
    s += ["lang|0"]
    for _ in range(400):
        s += fill(rnd.randrange(0, 7), rnd.randrange(0, 4),
                  rnd.choice((0, 0, 1)), rnd.randrange(0, 2),
                  rnd.choice((0, 5, 5, 3)), rnd.randrange(1, 9),
                  rnd.randrange(0, 9), rnd.randrange(0, 6),
                  rnd.randrange(0, 3), rnd.choice((0, 4, 5)),
                  rnd.choice((0, 1, 1, 1)),
                  tuple(rnd.choice((0, 0x7fffffff, rnd.randrange(1, 1 << 27)))
                        for _ in range(5)),
                  rnd.choice((0, rnd.randrange(1, 1 << 28))),
                  rnd.randrange(0, 5))
    return s


def script():
    rnd = random.Random(0x5eed0f)
    s = ["lang|0"] + english()
    # The formats alone.
    for place in range(0, 9):
        for i in (59010, 59017, 59018, 59019, 59011, 4):
            s.append("fpos|%d|%d" % (place, i))
    for lang in range(6):
        s.append("lang|%d" % lang)
        for v in (0, 1, 39, 40, 41, 4000, 39999, 40001, 240000, 2399980,
                  2399999, 14400000, 0x7fffffff, 0x7ffffffe, 0x80000000,
                  0xfffffff0):
            s += ["ftime|%d|59015" % v, "ftime|%d|59016" % v]
    s += ["lang|0", "ftime|400000|7", "str|7|%s and more", "ftime|400000|7",
          "fpos|4|7"]
    s += wrap_cases(rnd)
    s += fill_cases(rnd)
    return s


# =================================================================== model

class Model(object):
    def __init__(self):
        self.out = []
        e = self.e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.players = e.alloc(MAX_PLAYERS * PLAYER_SIZE)
        self.cars = e.alloc(MAX_CARS * CAR_SIZE)
        self.rcs = e.alloc(MAX_RC * RC_SIZE)
        self.race = e.alloc(RACE_SIZE)
        self.buf = e.alloc(256)
        for blk, n in ((self.players, MAX_PLAYERS * PLAYER_SIZE),
                       (self.cars, MAX_CARS * CAR_SIZE),
                       (self.rcs, MAX_RC * RC_SIZE), (self.race, RACE_SIZE)):
            e.write(blk, bytes(n))
        for i in range(MAX_CARS):
            e.put32(self.car(i) + 28, self.rc(i))
            e.put32(self.rc(i), self.car(i))
        e.write(RP, bytes(800))
        e.write(RACE_EVENT, bytes(400))
        e.put32(LANGUAGE, 0)
        e.put32(P_CUR_RACE, self.race)
        e.put32(BY_NUMBER, 0)
        e.put32(BY_NUMBER + 4, 0)

        self.strs = {}
        self.strings = {}
        self.use_event = 0
        self.height = 0.0
        self.chunks = []
        self.groups = {}

        for a, fn in ((S_TR, self.tr), (S_USETRE, self.usetre),
                      (S_KOSPEECH, self.kospeech), (S_FIND, self.find),
                      (S_VIS, self.vis), (S_SETSTR, self.setstr),
                      (S_HEIGHT, self.scaled_height)):
            e.stub(a, fn)

    def player(self, i):
        return self.players + PLAYER_SIZE * i

    def car(self, i):
        return self.cars + CAR_SIZE * i

    def rc(self, i):
        return self.rcs + RC_SIZE * i

    def emit(self, s):
        self.out.append(s)

    def cstr(self, a, n=4096):
        b = bytearray()
        mem = self.e.mem
        while len(b) < n and mem[a]:
            b.append(mem[a])
            a += 1
        return b.decode("latin-1")

    def string(self, s):
        """A NUL-terminated copy of s in emulated memory, made once."""
        a = self.strings.get(s)
        if a is None:
            raw = s.encode("latin-1") + b"\0"
            a = self.e.alloc(len(raw))
            self.e.write(a, raw)
            self.strings[s] = a
        return a

    def chunk_name(self, a):
        return "#%d" % self.chunks.index(a) if a in self.chunks else \
            "%08x" % a

    # ------------------------------------------------------------- stubs

    def tr(self, em):
        i = s32(em.reg[4])
        self.emit("  tr %d" % i)
        return self.string(self.strs.get(i, "T%d" % i))

    def usetre(self, em):
        self.emit("  usetre")
        return self.use_event & M32

    def kospeech(self, em):
        p = em.reg[4] & M32
        self.emit("  kospeech p%d %d" % ((p - self.players) // PLAYER_SIZE,
                                         s32(em.reg[5])))
        return 0

    def find(self, em):
        r = em.reg
        screen, group, typ, after = (r[4] & M32, r[5] & M32, s32(r[6]),
                                     r[7] & M32)
        self.emit("  find %08x %08x %d %s" % (
            screen, group, typ, self.chunk_name(after) if after else "-"))
        g = self.groups.get((screen, group))
        if g is None:
            return 0
        if after == 0:
            return g[0] if g else 0
        if after in g and g.index(after) + 1 < len(g):
            return g[g.index(after) + 1]
        return 0

    def vis(self, em):
        a = em.reg[4] & M32
        v = s32(em.reg[5])
        self.emit("  vis %s %d" % (self.chunk_name(a), v))
        self.e.write(a + 41, struct.pack("<b", v))
        return 0

    def setstr(self, em):
        self.emit("  str %s [%s]" % (self.chunk_name(em.reg[4] & M32),
                                     self.cstr(em.reg[5] & M32)))
        return 0

    def scaled_height(self, em):
        self.emit("  height %s" % self.chunk_name(em.reg[4] & M32))
        em.fpr[0] = fb(self.height)
        return 0

    # ---------------------------------------------------------------- ops

    def dump_vis(self):
        self.emit("  visible" + "".join(
            " %d" % struct.unpack("<b", bytes([self.e.mem[c + 41]]))[0]
            for c in self.chunks))

    def clear_stack(self):
        sp = self.e.reg[29] & M32
        self.e.write(sp - 8192, bytes(8192))

    def call(self, fn, *args):
        self.clear_stack()
        return self.e.call(fn, *args, limit=2000000)

    def op(self, a):
        e = self.e
        o = a[0]
        n = lambda k: int(a[k], 0)
        if o == "lang":
            e.put32(LANGUAGE, n(1) & M32)
        elif o == "rp":
            e.put32(RP + 32, n(1) & M32)
            e.put32(RP + 48, n(2) & M32)
            e.put32(RP + 628, n(3) & M32)
        elif o == "ev":
            self.use_event = n(1)
            e.write(RACE_EVENT + 106, struct.pack("<h", n(2)))
        elif o == "race":
            e.put32(self.race + 24, n(1) & M32)
            e.write(self.race + 1619, struct.pack("<b", n(2)))
        elif o == "rc":
            rc = self.rc(n(1))
            e.write(rc + 12, struct.pack("<b", n(2)))
            e.write(rc + 18, struct.pack("<h", n(3)))
            e.put32(rc + 180, n(4) & M32)
            for i in range(5):
                e.put32(rc + 96 + 4 * i, n(5 + i) & M32)
        elif o == "car":
            p = n(2)
            e.put32(self.car(n(1)) + 24, self.player(p) if p >= 0 else 0)
        elif o == "link":
            c = n(2)
            e.put32(self.rc(n(1)), self.car(c) if c >= 0 else 0)
        elif o == "player":
            p = self.player(n(1))
            e.put32(p + 16, n(2) & M32)
            e.put32(p + 772, n(3) & M32)
            e.put32(p + 4, self.car(n(4)))
        elif o == "bynum":
            p = n(2)
            e.put32(BY_NUMBER + 4 * n(1), self.player(p) if p >= 0 else 0)
        elif o == "str":
            self.strs[n(1)] = a[2]
        elif o == "grp":
            y = struct.unpack("<f", struct.pack("<I", n(3)))[0]
            g = []
            for k, m in enumerate(a[4:]):
                maxc = int(m, 0)
                c = e.alloc(100 + maxc + 1)
                e.write(c, bytes(100 + maxc + 1))
                e.write(c + 40, struct.pack("<bb", 1, 7))
                e.write(c + 52, struct.pack("<f", y + 20.0 * k))
                e.put32(c + 84, maxc & M32)
                self.chunks.append(c)
                g.append(c)
            self.groups[(n(1) & M32, n(2) & M32)] = g
        elif o == "height":
            self.height = struct.unpack("<f", struct.pack("<I", n(1)))[0]
        elif o == "fill":
            self.call(F_FILL, self.player(n(1)))
            self.dump_vis()
        elif o == "rtig":
            txt = a[3] if len(a) > 3 else ""
            r = self.call(F_RTIG, n(1) & M32, n(2) & M32, self.string(txt))
            self.emit("  = %d" % s32(r))
            self.dump_vis()
        elif o == "fpos":
            e.write(self.buf, bytes(256))
            self.call(F_FPOS, self.buf, n(1) & M32, n(2) & M32)
            self.emit("  [%s]" % self.cstr(self.buf))
        elif o == "ftime":
            t = e.alloc(4)
            e.put32(t, n(1) & M32)
            e.write(self.buf, bytes(256))
            self.call(F_FTIME, self.buf, t, n(2) & M32)
            self.emit("  [%s]" % self.cstr(self.buf))
        else:
            self.emit("  ?")

    def run(self, lines):
        e = self.e
        for line in lines:
            self.emit("> " + line)
            sp = e.reg[29]
            # The harness's strtok drops empty fields.
            self.op([f for f in line.split("|") if f != ""] or [""])
            e.reg[29] = sp
        return self.out


# The line the mutations start at, spelt so that this one does not match.
MUTATIONS_HEADER = "# " + "=" * 60 + " the mutations" + NL


def model_cached(sc):
    """Model().run(sc), or its last transcript when nothing it reads has
    changed (tools/mutpar.py)."""
    return mutpar.model_cached(sc, lambda s: Model().run(s),
                               cut=MUTATIONS_HEADER)


# ================================================================= build

def build_harness(tmp, name="raceover_test"):
    return hostbuild.build(tmp, SOURCES, name=name)


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


def encode(lines):
    return NL.join(lines) + NL


# ============================================================ the mutations


def M(name, before, after, rel=RO):
    return (name, rel, before, after)


MUTATIONS = [
    # The timer's rounding.
    M("t-round", "timer_set_time(&r, timer_round_seconds(t, f));",
      "timer_set_time(&r, timer_round_seconds(t, f * 10.0f));", TIMER),
    M("t-unround", "timer_set_time(&r, timer_round_seconds(t, f));",
      "r = *t;", TIMER),
    M("t-flags", "timer_print_to_string(&r, buf, flags, language);",
      "timer_print_to_string(&r, buf, flags | 2, language);", TIMER),
    M("rounding", "#define TIME_ROUNDING 0.01f", "#define TIME_ROUNDING 0.1f"),
    M("time-lang", "TIME_ROUNDING, 0, language());",
      "TIME_ROUNDING, 0, 0);"),

    # The formats.
    M("place-0", "    321001, 61009, 321003,", "    321002, 61009, 321003,"),
    M("place-1", "    321001, 61009, 321003,", "    321001, 321002, 321003,"),
    M("place-8", "321008, 321009,\n};", "321008, 321008,\n};"),
    M("place-range", "if (place >= 0 && place < NUM_PLACES)",
      "if (place > 0 && place < NUM_PLACES)"),
    M("place-order", "    b_snprintf(fmt, sizeof fmt, \"%s\", translate(id));\n"
      "    if (place >= 0 && place < NUM_PLACES)\n"
      "        word = translate(kPlaceIds[place]);",
      "    if (place >= 0 && place < NUM_PLACES)\n"
      "        word = translate(kPlaceIds[place]);\n"
      "    b_snprintf(fmt, sizeof fmt, \"%s\", translate(id));"),
    M("fmt-held", "    b_snprintf(fmt, sizeof fmt, \"%s\", translate(id));\n"
      "    if (place >= 0 && place < NUM_PLACES)\n"
      "        word = translate(kPlaceIds[place]);\n"
      "    b_snprintf(buf, MESSAGE_BYTES, fmt, word);",
      "    const char *held = translate(id);\n"
      "    if (place >= 0 && place < NUM_PLACES)\n"
      "        word = translate(kPlaceIds[place]);\n"
      "    (void)fmt;\n"
      "    b_snprintf(buf, MESSAGE_BYTES, held, word);"),
    M("tr-null", "    return s != NULL ? s : \"\";",
      "    return s != NULL ? s : \"?\";"),

    # The message's choices.
    M("tt-valid", "            if (timer_is_valid(&best))",
      "            if (best.PackedTime != 0)"),
    M("tt-arrest-lap", "race_over_format_time(buf, &best, MSG_ARRESTED_LAP);",
      "race_over_format_time(buf, &race, MSG_ARRESTED_LAP);"),
    M("tt-nolap", "                id = MSG_ARRESTED_NO_LAP;",
      "                id = MSG_ARRESTED;"),
    M("tt-lap", "race_over_format_time(buf, &best, MSG_LAP_TIME);",
      "race_over_format_time(buf, &race, MSG_LAP_TIME);"),
    M("tt-reason", "        } else if (reason == RACING_CAR_NORMAL_COMPLETION) {\n"
      "            race_over_format_time(buf, &best, MSG_LAP_TIME);",
      "        } else {\n"
      "            race_over_format_time(buf, &best, MSG_LAP_TIME);"),
    M("ko-arrest", "    case RACE_TYPE_RACE_KNOCKOUT:\n"
      "        if (reason == RACING_CAR_ARRESTED) {",
      "    case RACE_TYPE_RACE_KNOCKOUT:\n"
      "        if (reason == RACING_CAR_KNOCKED_OUT) {"),
    M("ko-last", "                   || place == pCurrentRace->NumRacingCars) {",
      "                   || place >= pCurrentRace->NumRacingCars) {"),
    M("ko-out-id", "race_over_format_finish_position(buf, place, MSG_KNOCKED_OUT);",
      "race_over_format_finish_position(buf, place, MSG_KNOCKED_OUT_LAP);"),
    M("ko-out-speech", "MSG_KNOCKED_OUT);\n            knockout_speech(p, 0);",
      "MSG_KNOCKED_OUT);\n            knockout_speech(p, 1);"),
    M("ko-advance", "                pCurrentRace->NumRacingCars >= "
      "KNOCKOUT_ADVANCE_CARS",
      "                pCurrentRace->NumRacingCars > KNOCKOUT_ADVANCE_CARS"),
    M("ko-advance-id", "                    ? MSG_ADVANCE : MSG_FINISHED);",
      "                    ? MSG_FINISHED : MSG_ADVANCE);"),
    M("ko-speech", "MSG_FINISHED);\n            knockout_speech(p, 1);",
      "MSG_FINISHED);\n            knockout_speech(p, 0);"),
    M("lko-arrest", "    case RACE_TYPE_LAP_KNOCKOUT:\n"
      "        if (reason == RACING_CAR_ARRESTED) {\n"
      "            id = MSG_ARRESTED;",
      "    case RACE_TYPE_LAP_KNOCKOUT:\n"
      "        if (reason == RACING_CAR_ARRESTED) {\n"
      "            id = MSG_ARRESTED_NO_END;"),
    M("lko-out", "MSG_KNOCKED_OUT_LAP);\n            knockout_speech(p, 0);",
      "MSG_KNOCKED_OUT_LAP);"),
    M("lko-else", "        } else {\n"
      "            race_over_format_finish_position(buf, place, MSG_FINISHED);"
      "\n        }",
      "        } else {\n"
      "            race_over_format_finish_position(buf, place, MSG_FINISHED);"
      "\n            knockout_speech(p, 1);\n        }"),
    M("tourney-case", "    case RACE_TYPE_SINGLE_RACE:\n"
      "    case RACE_TYPE_TOURNAMENT:", "    case RACE_TYPE_SINGLE_RACE:"),
    M("default", "    default:\n        break;\n    }",
      "    default:\n        id = MSG_FINISHED;\n        break;\n    }"),
    M("cop-test", "        if (TheRaceParameters.BeACop != 0) {",
      "        if (TheRaceParameters.BeACop > 1) {"),
    M("event-type", "&& TheRaceEventFields.Type == RACE_EVENT_POINT2POINT) {",
      "&& TheRaceEventFields.Type >= RACE_EVENT_POINT2POINT) {"),
    M("event-order", "        } else if (fred_use_the_race_event(&Fred)\n"
      "                   && TheRaceEventFields.Type == RACE_EVENT_POINT2POINT)"
      " {",
      "        } else if (TheRaceEventFields.Type == RACE_EVENT_POINT2POINT\n"
      "                   && fred_use_the_race_event(&Fred)) {"),
    M("event-arrest", "                id = MSG_ARRESTED_NO_END;",
      "                id = MSG_ARRESTED;"),
    M("event-time", "race_over_format_time(buf, &race, MSG_TIME);",
      "race_over_format_time(buf, &best, MSG_TIME);"),
    M("single-arrest", "                reason == RACING_CAR_ARRESTED ? "
      "MSG_ARRESTED : MSG_FINISHED);",
      "                reason == RACING_CAR_KNOCKED_OUT ? "
      "MSG_ARRESTED : MSG_FINISHED);"),
    M("render-group", "flailer_render_text_into_group(p->HudScreenHash, "
      "RACE_OVER_MESSAGE_GROUP,",
      "flailer_render_text_into_group(p->HudScreenHash, 0xc707e094u,"),
    M("place-int8", "    int32_t place = rc->FinishingOrder;",
      "    int32_t place = (uint8_t)rc->FinishingOrder;"),

    # You're The Cop.
    M("cop-np1", "        return reason == RACING_CAR_BE_THE_COP_WON ? "
      "MSG_ARRESTED_ALL\n                                                   "
      ": MSG_QUOTA;",
      "        return reason == RACING_CAR_BE_THE_COP_LOST ? MSG_QUOTA\n"
      "                                                    : "
      "MSG_ARRESTED_ALL;"),
    M("cop-np2", "if (TheRaceParameters.NumPlayerCars != 2 || pl == NULL)",
      "if (pl == NULL)"),
    M("cop-p0-win", "            return MSG_P1_WIN;", "            return MSG_P2_WIN;"),
    M("cop-p0-lose", "            return other_lost(1) ? MSG_OUT_OF_TIME : "
      "MSG_P1_LOSE;",
      "            return other_lost(0) ? MSG_OUT_OF_TIME : MSG_P1_LOSE;"),
    M("cop-p0-else", "            return other_lost(1) ? MSG_OUT_OF_TIME : "
      "MSG_P1_LOSE;\n        return 0;",
      "            return other_lost(1) ? MSG_OUT_OF_TIME : MSG_P1_LOSE;\n"
      "        if (reason == RACING_CAR_NORMAL_COMPLETION)\n"
      "            return MSG_P1_WIN;\n        return 0;"),
    M("cop-p1-num", "    if (pl->PlayerNumber == 1) {",
      "    if (pl->PlayerNumber != 0) {"),
    M("cop-p1-lose", "            return other_lost(0) ? MSG_OUT_OF_TIME : "
      "MSG_P2_LOSE;",
      "            return other_lost(0) ? MSG_P2_LOSE : MSG_OUT_OF_TIME;"),
    M("cop-p1-done", "        if (reason == RACING_CAR_NORMAL_COMPLETION)\n"
      "            return MSG_P2_WIN;",
      "        if (reason == RACING_CAR_NORMAL_COMPLETION)\n"
      "            return MSG_P2_LOSE;"),
    M("cop-lost", "                  == RACING_CAR_BE_THE_COP_LOST;",
      "                  != RACING_CAR_BE_THE_COP_WON;"),
    M("cop-player", "    const struct Player *pl = racingcar_get_player(rc);",
      "    const struct Player *pl = PlayerPlayersByNumber[0];"),

    # RenderTextIntoGroup.
    M("w-max", "#define WRAP_MAX_OBJECTS 32", "#define WRAP_MAX_OBJECTS 31",
      FW),
    M("w-space-tab", "    return c == ' ' || c == '\\t' || c == 0;",
      "    return c == ' ' || c == 0;", FW),
    M("w-at", "            if (is_space(*p) || *p == '@') {",
      "            if (is_space(*p)) {", FW),
    M("w-room", "} else if (n < maxc - 2 && (n++, *p != '@')) {",
      "} else if (n < maxc - 1 && (n++, *p != '@')) {", FW),
    M("w-room-at", "} else if (n < maxc - 2 && (n++, *p != '@')) {",
      "} else if (n < maxc - 2) {\n                n++;", FW),
    M("w-count-plain", "            if (!brk) {\n                n++;",
      "            if (!brk) {\n                n += 2;", FW),
    M("w-flush-line", "write_text_into_chunk(chunks[cur], line, brk_at);",
      "write_text_into_chunk(chunks[cur], line, brk_at + 1);", FW),
    M("w-skip", "                p = brk_at + 1;\n                line = p;",
      "                p = brk_at;\n                line = p + 1;", FW),
    M("w-maxc", "                maxc = chunks[cur]->MaxChars;",
      "                maxc = chunks[0]->MaxChars;", FW),
    M("w-brk", "                brk = 0;\n                next = cur + 1;",
      "                next = cur + 1;", FW),
    M("w-n0", "                n = 0;\n                if (chunks[cur]",
      "                n = 1;\n                if (chunks[cur]", FW),
    M("w-runout", "                if (chunks[cur] == NULL)\n"
      "                    return 0;",
      "                if (chunks[cur] == NULL)\n"
      "                    break;", FW),
    M("w-last", "    last = chunks[next] != NULL ? chunks[next] : "
      "chunks[next - 1];",
      "    last = chunks[next - 1];", FW),
    M("w-hide", "    for (i = next; i < count; i++)",
      "    for (i = next + 1; i < count; i++)", FW),
    M("w-hide-call", "        chunks[i]->Object.Visibility = "
      "FLAILER_OBJECT_INVISIBLE;",
      "        flailerobject_set_visibility(&chunks[i]->Object, 0);", FW),
    M("w-answer", "    return ee_trunc_w(last->Object.Y + h);",
      "    return ee_trunc_w(last->Object.Y + h + 0.5f);", FW),
    M("w-empty", "    if (count == 0)\n        return 0;",
      "    if (count == 0 || *str == 0)\n        return 0;", FW),
    M("w-vis", "    flailerobject_set_visibility(&t->Object, "
      "FLAILER_OBJECT_VISIBLE);\n", "", FW),
    M("w-type", "flailer_find_object_by_group(screen, group,\n"
      "                                                FLAILER_TYPE_TEXT, o))",
      "flailer_find_object_by_group(screen, group,\n"
      "                                                FLAILER_TYPE_ANY, o))",
      FW),
]

EQUIVALENT = {
    "tr-null": "the seam's fallback; retail's GetTranslatedString never "
               "answers NULL",
    "place-int8": "the place's sign tells only for a place outside 0 to 8, "
                  "whose word retail reads from outside the table",
}

for _name in EQUIVALENT:
    assert any(_m[0] == _name for _m in MUTATIONS), _name


def mutate_pass(only=None, jobs=None):
    todo = [m for m in MUTATIONS if only is None or m[0] in only]
    if only:
        unknown = set(only) - {m[0] for m in MUTATIONS}
        if unknown:
            print("no such mutation: %s" % ", ".join(sorted(unknown)))
            return 1
    sc = script()
    base = model_cached(sc)
    scdir = tempfile.TemporaryDirectory()
    scp = Path(scdir.name) / "script.txt"
    scp.write_bytes(encode(sc).encode("latin-1"))
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        out = Path(tmp) / "base.txt"
        t0 = time.monotonic()
        run_harness(exe, scp, out)
        took = time.monotonic() - t0
        got = out.read_text(encoding="latin-1").splitlines()
        if diff(base, got, quiet=True):
            print("base already differs -- fix that before mutating")
            return 1
        print("base: %d lines, 0 differ" % len(got), flush=True)

    limit = mutpar.timeout_for(took)
    tally = mutpar.run_pass(
        todo, SOURCES, "raceover_test",
        lambda exe, out: mutpar.run_exe([exe, scp], out, limit),
        base, diff, EQUIVALENT, jobs)
    scdir.cleanup()
    return mutpar.summarize(todo, only, EQUIVALENT, tally)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("--only", metavar="NAME,...",
                    help="with --mutate, only these mutations")
    ap.add_argument("--jobs", type=int, metavar="N",
                    help="with --mutate, mutants at once (default %d)"
                    % mutpar.JOBS)
    ap.add_argument("--dump", metavar="PREFIX")
    args = ap.parse_args()

    if args.mutate:
        sys.exit(mutate_pass(args.only.split(",") if args.only else None,
                             args.jobs))

    sc = script()
    lines = model_cached(sc)
    with tempfile.TemporaryDirectory() as tmp:
        exe = build_harness(tmp)
        scp = Path(tmp) / "script.txt"
        scp.write_bytes(encode(sc).encode("latin-1"))
        out = Path(tmp) / "harness.txt"
        rc = run_harness(exe, scp, out)
        harness = out.read_text(encoding="latin-1").splitlines()

    if args.dump:
        d = Path(args.dump)
        d.parent.mkdir(parents=True, exist_ok=True)
        d.with_suffix(".model").write_text(NL.join(lines) + NL)
        d.with_suffix(".harness").write_text(NL.join(harness) + NL)

    n = diff(lines, harness)
    print("%d ops, %d lines, %d differ" % (len(sc), len(harness), n))
    sys.exit(1 if (n or rc) else 0)


if __name__ == "__main__":
    main()
