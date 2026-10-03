#!/usr/bin/env python3
"""Cross-check 3DS Files/source/bprintf.c, the port's bSPrintf, against the
retail image, SLES_507.31.

**The model** is retail's bSPrintf (0x00251398), run in
retail_model.RetailEmu with the arguments in the EABI registers -- a float
as a double, as a varargs call passes it. Retail has no bound, so a buffer
of SIZE bytes is modelled as snprintf's contract: the first SIZE - 1 bytes
of what retail wrote, and retail's whole length as the answer. The harness
(tools/src/bprintf_test.c) calls b_snprintf with a guard behind the buffer.

**The script** runs every %f form the game's strings use, and the flags,
widths and precisions around them, over values that tie at each place, fall
either side of one, are -0 or round to it, and some at random; then the
integer, character, string and pointer conversions, the size letters, '*',
the letters retail does not know, the HUD's own formats, and buffers too
small for what they are given.

Not compared, and documented in bprintf.h: %e, %g, %F, %z and %t, which
nothing the port prints uses, and %f past about 1e23, where retail's digits
drift from the exact value.

    python tools/bprintf_check.py
    python tools/bprintf_check.py --mutate [--only a,b]
    python tools/bprintf_check.py --dump out/bprintf
"""
import argparse
import os
import random
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hostbuild                        # noqa: E402
import physicscar_check as pcc          # noqa: E402
import retail_model                     # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NL = chr(10)

HARNESS = "tools/src/bprintf_test.c"
BPRINTF = "3DS Files/source/bprintf.c"
SOURCES = [HARNESS, BPRINTF]
HARNESS_TIMEOUT = 60

F_BSPRINTF = 0x00251398

# The argument lists the harness can make; bprintf_test.c's call() has the
# same.
TYPES = {"", "f", "d", "s", "p", "dd", "df", "dp", "ds", "sd", "sf", "ff",
         "ddd", "ddf", "ddp", "dfd", "fff", "sdf", "fffd", "ffffff"}


def f32(v):
    return struct.unpack("<f", struct.pack("<f", v))[0]


def fbits(v):
    return struct.unpack("<I", struct.pack("<f", v))[0]


# ================================================================= script

def op(size, fmt, types="", *args):
    assert types in TYPES, types
    assert len(args) == len(types)
    out = ["p", str(size), fmt.encode().hex() or "00", types or "-"]
    for t, a in zip(types, args):
        if t == "f":
            out.append("%08x" % fbits(a))
        elif t == "d":
            out.append(str(a))
        elif t == "s":
            out.append(a.encode().hex() or "00")
        else:
            out.append("%x" % a)
    return "|".join(out)


BIG = 4096

F_FORMATS = ["%f", "%.0f", "%.1f", "%.2f", "%.3f", "%.4f", "%.6f", "%.9f",
             "%3.0f", "%3.1f", "%5.1f %%", "%f km", "%8.3f", "%-6.1f|",
             "%06.1f", "%+.1f", "% .1f", "%#.0f", "%.f", "%5.f|", "%010.2f",
             "%-10.2f|", "% 06.1f", "%12f|", "%+.0f", "%lf", "%Lf", "%hf"]

F_VALUES = [
    0.0, -0.0, 1.0, -1.0, 0.5, 1.5, 2.5, -0.5, -1.5, -2.5, 3.5,
    0.25, 0.75, -0.25, -7.25, 0.125, 0.375, -0.125, 0.0625, 0.03125,
    0.0005, 0.0015, 0.0025, -0.0005, 0.00005, 1e-5, 1e-9,
    0.04, -0.04, -0.4, -0.45, 0.05, 0.15, 0.95, 9.95, 99.95, 9.995,
    1.005, 2.675, 12.3455, 12.3454, 33.333, 33.3349, 0.3333, 2.0 / 3,
    59.95, 59.99, 999.9999, 100.0, 125.5, -1234.5, 98765.0,
    4194304.5, 8388607.5, 16777215.0, 16777217.0, 123456789.0, 1e7 + 0.5,
    1e10, 2.0 ** 40, 1e20, 1e22, -1e15, 3.1415927, -3.14159, 6.02e-23,
    1e-38, 1.17549435e-38, 1e-45,
]

I_FORMATS = ["%d", "%5d", "%-5d|", "%05d", "%+d", "% d", "%+ d", "%.3d",
             "%.0d", "%-05d|", "%-+5d|", "%x", "%X", "%08X", "%#x", "%#.3x",
             "%.0x", "%#o", "%o", "%u", "%i", "%hd", "%hu", "%hx", "%hhd",
             "%hhx", "%hhhd", "%lhd", "%hld", "%Lhd", "%ld", "%lld", "%Ld",
             "%lu", "%c", "%5c|", "%-3c|", "%lc", "%hc"]

I_VALUES = [0, 1, -1, 5, 42, -17, 65, 255, 300, 321, 511, 4464, 32767,
            32768, 65535, 65536, 70000, -70000, 74565, 123456789,
            0x7fffffff, -0x80000000, -2]

S_FORMATS = ["%s", "%10s|", "%-10s|", "%.3s", "%5.2s|", "%.0s|", "%ls",
             "%hs", "%2s|", "[%s]"]

S_VALUES = ["Hello", "", "A", "DRV0", "A much longer string than ten",
            "with %d in it", "tab\tand space"]


def s_floats(rng):
    vals = list(F_VALUES)
    for _ in range(60):
        vals.append(round(rng.uniform(-1000, 1000), rng.randint(0, 4)))
    for _ in range(20):
        # a tie at some place, exactly: k / 2^n
        vals.append(rng.randint(-4000, 4000) / 2.0 ** rng.randint(1, 8))
    for _ in range(20):
        vals.append(rng.uniform(-1, 1) * 10.0 ** rng.randint(-6, 9))
    out = []
    for fmt in F_FORMATS:
        for v in vals:
            out.append(op(BIG, fmt, "f", f32(v)))
    return out


def s_integers():
    out = []
    for fmt in I_FORMATS:
        for v in I_VALUES:
            if "c" in fmt and v == 0:
                continue
            out.append(op(BIG, fmt, "d", v))
    return out


def s_strings():
    return [op(BIG, fmt, "s", v) for fmt in S_FORMATS for v in S_VALUES]


def s_stars():
    return [
        op(BIG, "%*d", "dd", 6, 42), op(BIG, "%*d", "dd", -6, 42),
        op(BIG, "%*d", "dd", 0, 42), op(BIG, "%-*d|", "dd", 6, 42),
        op(BIG, "%0*d", "dd", 5, 42), op(BIG, "%0*d", "dd", 5, -42),
        op(BIG, "%.*d", "dd", -1, 42), op(BIG, "%.*d", "dd", 4, 42),
        op(BIG, "%.*d", "dd", 0, 0), op(BIG, "%*c|", "dd", 3, 66),
        op(BIG, "%.*f", "df", 2, 3.14159), op(BIG, "%.*f", "df", -1, 1.5),
        op(BIG, "%.*f", "df", -1, 12.3455), op(BIG, "%.*f", "df", 0, 2.5),
        op(BIG, "%.*f", "df", 1, 0.25), op(BIG, "%.*f", "df", 3, -0.0005),
        op(BIG, "%*.*f", "ddf", 8, 2, 3.14159),
        op(BIG, "%*.*f", "ddf", -8, 1, -0.25),
        op(BIG, "%*.*f|", "ddf", 9, -1, 2.0 / 3),
        op(BIG, "%*.*d|", "ddd", 7, 4, -42),
        op(BIG, "%*f|", "df", 10, 0.0625),
        op(BIG, "%*s|", "ds", 8, "Hi"), op(BIG, "%-*s|", "ds", 8, "Hi"),
        op(BIG, "%.*s", "ds", 2, "Hello"), op(BIG, "%.*s|", "ds", -1, "Hey"),
    ]


def s_misc():
    return [
        op(BIG, "%%"), op(BIG, "abc"), op(BIG, ""), op(BIG, "%5%|"),
        op(BIG, "100%% sure %%%%"), op(BIG, "abc%"), op(BIG, "%5"),
        op(BIG, "x%-"), op(BIG, "%l"), op(BIG, "%hh"),
        op(BIG, "%q%d", "d", 1), op(BIG, "%k|"), op(BIG, "%5k|"),
        op(BIG, "%j"), op(BIG, "%jd", "d", 5), op(BIG, "%qd", "d", 5),
        op(BIG, "%m%r%A%Z%a%D%H%U"), op(BIG, "%.3q|"),
        op(BIG, "%s|", "p", 0), op(BIG, "%10s|", "p", 0),
        op(BIG, "%n%d", "sd", "", 4), op(BIG, "a%nb", "s", ""),
        op(BIG, "%p", "p", 0x1234), op(BIG, "%5p|", "p", 0x1234),
        op(BIG, "%-12p|", "p", 0x1234), op(BIG, "%p", "p", 0xdeadbeef),
        op(BIG, "%12p|", "p", 0), op(BIG, "%.2p|", "p", 0xabc),
        op(BIG, "%.*p|", "dp", 3, 0x1234),
        op(BIG, "%*.*p|", "ddp", 12, 3, 0xabc),
        op(BIG, "%600d|", "d", 7), op(BIG, "%-700s|", "s", "wide"),
        op(BIG, "%.40f", "f", 1.0 / 3),
        op(BIG, "%300.3f|", "f", -2.5),
    ]


def s_game():
    # The forms the port prints: hudrender.c, flailer_printf's callers.
    out = []
    for a, b, c, s in [(-1234.5, 0.0, 98765.0, 7), (0.4, -0.4, 2.5, 0),
                       (1e6 + 0.5, -0.5, 0.5, -3)]:
        out.append(op(BIG, "%.0f %.0f %.0f s%d", "fffd", a, b, c, s))
    for v in [0, 7, 30, 60, 999]:
        out.append(op(BIG, "C: %dfps", "d", v))
        out.append(op(BIG, "G: %dfps", "d", v))
        out.append(op(BIG, "+%d", "d", v))
    for v in [0.0, 0.05, 9.95, 9.96, 10.0, 10.04, 59.5, 123.45]:
        out.append(op(BIG, "%3.0f", "f", v))
        out.append(op(BIG, "%3.1f", "f", v))
    for v in [0.0, 0.0005, 12.3455, 1234.5675]:
        out.append(op(BIG, "%f km", "f", v))
    out += [
        op(BIG, "%d:%02d.%02d", "ddd", 1, 5, 9),
        op(BIG, "%s %d %f", "sdf", "Lap", 3, 81.25),
        op(BIG, "%f %f %f %f %f %f", "ffffff", 1, 2, 3, 0.5, -0.5, 1e-4),
        op(BIG, "%s%f", "sf", "t=", 0.0015),
        op(BIG, "%.2f %.2f", "ff", 0.125, -0.125),
        op(BIG, "%.1f %.1f %.1f", "fff", 0.05, 0.15, 0.25),
        op(BIG, "%d %.1f %d", "dfd", 3, 99.95, -4),
    ]
    return out


def s_sizes():
    out = []
    cases = [("%f km", "f", (12.3455,)), ("%s %d", "sd", ("Hello", 12345)),
             ("abc%ddef", "d", (7,)), ("%10s|", "s", ("Hi",)),
             ("%%%d%%", "d", (5,)), ("ab%kcd", "", ()), ("", "", ()),
             ("%.0f %.0f %.0f s%d", "fffd", (-1234.5, 0.0, 98765.0, 7)),
             ("%600d|", "d", (7,))]
    for fmt, t, args in cases:
        for size in (0, 1, 2, 3, 5, 8, 9, 10, 17):
            out.append(op(size, fmt, t, *args))
    return out


def script():
    rng = random.Random(7)
    return (s_floats(rng) + s_integers() + s_strings() + s_stars()
            + s_misc() + s_game() + s_sizes())


# ================================================================== model

class Model(object):
    def __init__(self):
        e = retail_model.RetailEmu(ieee=True)
        e.stub_bware()
        self.e = e
        self.buf = e.alloc(BIG + 64)
        self.fmt = e.alloc(256)
        self.strs = [e.alloc(256) for _ in range(6)]
        self.out = []

    def call(self, size, fmt, types, args):
        e = self.e
        regs = []
        for i, (t, a) in enumerate(zip(types, args)):
            if t == "f":
                b = int(a, 16)
                d = struct.unpack("<f", struct.pack("<I", b))[0]
                regs.append(struct.unpack("<Q", struct.pack("<d", d))[0])
            elif t == "d":
                regs.append(int(a))
            elif t == "s":
                s = bytes.fromhex(a)
                s = s[:s.index(0)] if 0 in s else s
                e.write(self.strs[i], s + b"\0")
                regs.append(self.strs[i])
            else:
                regs.append(int(a, 16))
        e.write(self.fmt, fmt + b"\0")
        e.write(self.buf, b"\xee" * (BIG + 64))
        r = e.call(F_BSPRINTF, self.buf, self.fmt, *regs, limit=20000000)
        n = 0
        while e.mem[self.buf + n]:
            n += 1
        full = bytes(e.mem[self.buf:self.buf + n])
        shown = full[:size - 1] if size else b""
        return r, shown.decode("latin-1")

    def run(self, lines):
        for line in lines:
            self.out.append("> " + line)
            tok = line.split("|")
            types = "" if tok[3] == "-" else tok[3]
            r, s = self.call(int(tok[1]), bytes.fromhex(tok[2]), types,
                             tok[4:])
            self.out.append('  %d "%s"' % (r, s))
        return self.out


def model(lines):
    return Model().run(lines)


# ================================================================= build

def build_harness(tmp, name="bprintf_test"):
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


def write_script(d, lines):
    sc = Path(d) / "script.txt"
    sc.write_text(NL.join(lines) + NL)
    return sc


def read_out(path):
    return path.read_text(encoding="latin-1").splitlines()


# ============================================================= mutations

B = BPRINTF
MUTATIONS = [
    # The rounding.
    ("round-just-under-half", B, "floor(m * p10 + 0.5)",
     "floor(m * p10 + 0.4999)"),
    ("round-down", B, "r = floor(m * p10 + 0.5) / p10;",
     "r = floor(m * p10) / p10;"),
    ("round-half-down", B, "floor(m * p10 + 0.5)", "ceil(m * p10 - 0.5)"),
    ("round-sign-at-zero", B, "return v < 0.0 ? -r : r;",
     "return v <= 0.0 ? -r : r;"),
    ("round-no-sign", B, "return v < 0.0 ? -r : r;", "return r;"),
    ("round-copysign", B, "return v < 0.0 ? -r : r;",
     "return copysign(r, v);"),
    ("round-only-to-2", B, "if (prec > 15)", "if (prec > 2)"),
    ("round-power-off", B, "for (i = 0; i < prec; i++)",
     "for (i = 0; i <= prec; i++)"),
    ("round-limit-2^20", B, "if (m * p10 >= 4503599627370496.0)",
     "if (m * p10 >= 1048576.0)"),

    # Appending the text between conversions.
    ("put-no-room-for-nul", B,
     "size_t c = (size_t)k < room ? (size_t)k : room - 1;",
     "size_t c = (size_t)k < room ? (size_t)k : room;"),
    ("put-fits-exactly", B, "size_t c = (size_t)k < room ?",
     "size_t c = (size_t)k <= room ?"),
    ("put-at-end", B, "    if (*len < n) {", "    if (*len <= n) {"),
    ("put-counts-what-fits", B, "    *len += (size_t)k;" + NL + "}",
     "    if (*len < n)" + NL + "        *len += (size_t)k;" + NL + "}"),
    ("no-first-nul", B, "    if (n > 0)" + NL + "        out[0] = '\\0';",
     ""),
    ("room-one-short", B, "room = len < n ? n - len : 0;",
     "room = len < n ? n - len - 1 : 0;"),

    # The spec's parse.
    ("flags-no-space-hash", B, 'strchr("-+ #0", *fmt)',
     'strchr("-+0", *fmt)'),
    ("star-width-not-read", B,
     "        if (star_w)" + NL + "            w = va_arg(ap, int);" + NL,
     ""),
    ("precision-last-digit", B, "prec = prec * 10 + (*fmt++ - '0');",
     "prec = (*fmt++ - '0');"),
    ("dot-alone-is-none", B,
     "            prec = 0;" + NL + "            if (*fmt == '*')",
     "            prec = -1;" + NL + "            if (*fmt == '*')"),
    ("star-neg-precision-0", B, "prec = pr < 0 ? -1 : pr;",
     "prec = pr < 0 ? 0 : pr;"),
    ("h-last-letter-only", B, "h |= *fmt++ == 'h';", "h = *fmt++ == 'h';"),
    ("size-no-L", B, "while (*fmt == 'h' || *fmt == 'l' || *fmt == 'L')",
     "while (*fmt == 'h' || *fmt == 'l')"),
    ("no-break-at-end", B,
     "        if (conv == '\\0')" + NL + "            break;" + NL, ""),
    ("long-spec-at-4", B, "if (k >= sizeof spec - 5)", "if (k >= 4)"),

    # The conversions.
    ("f-default-6", B, "spec[k++] = '3';", "spec[k++] = '6';"),
    ("f-star-default-6", B, "                    pr = 3;" + NL,
     "                    pr = 6;" + NL),
    ("f-not-rounded", B, "            v = round_half_away(v, prec);" + NL,
     ""),
    ("f-rounded-a-place-on", B, "v = round_half_away(v, prec);",
     "v = round_half_away(v, prec + 1);"),
    ("h-ignored", B, "if (h && conv != 'c')", "if (0)"),
    ("h-on-c-too", B, "if (h && conv != 'c')", "if (h)"),
    ("p-lower-case", B, 'memcpy(spec + k, ".8X", 4);',
     'memcpy(spec + k, ".8x", 4);'),
    ("p-not-padded", B, 'memcpy(spec + k, ".8X", 4);',
     'memcpy(spec + k, "X", 2);'),
    ("p-keeps-precision", B,
     "            k = (size_t)(wend - start);" + NL, ""),
    ("n-takes-nothing", B,
     "            (void)va_arg(ap, void *);" + NL, ""),
    ("unknown-dropped", B,
     "            put(out, n, &len, 1, &conv);" + NL, ""),
    ("unknown-takes-arg", B,
     "            put(out, n, &len, 1, &conv);" + NL + "            got = 0;",
     "            put(out, n, &len, 1, &conv);" + NL
     + "            (void)va_arg(ap, int);" + NL + "            got = 0;"),
]

EQUIVALENT = {
    # The C library ignores h on %c, the host's and the 3DS's newlib both;
    # the test keeps %hc clear of what the standard leaves undefined.
    "h-on-c-too",
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
        if diff(base, read_out(out), quiet=True):
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
                n = diff(base, read_out(out), quiet=True)
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
        harness = read_out(out)

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
