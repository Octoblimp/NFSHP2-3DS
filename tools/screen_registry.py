#!/usr/bin/env python3
r"""Recover the Flailer screen registry out of NFSHP2.ELF.

Every frontend screen the game can `ChangeToScreen("...")` to is registered by
a *global constructor* that builds a `FlailerScreenConfig`:

    FlailerScreenConfig(const char *ScreenName,
                        void (*Callback)(ScreenMessage, ScreenCallbackData *),
                        int FlailerHash0, JoystickPort Port0,
                        int FlailerHash1, JoystickPort Port1,
                        int *HelpMenuItems);

`Populate__19FlailerScreenConfig...` (0x00166150) stores the name at +8 and the
callback at +12, appends each non-zero hash to `FlailerHashes[4]` with its port
in `Ports[4]`, and links the config into the global `FlailerScreenConfigList`
(0x003236c0).  `FlailerScreenList::FindScreen(name)` walks that list, so the
(name -> hash -> callback) triple recovered here is the whole mapping from the
string literals in the game's flow code ("New Main Menu", "Title Screen", ...)
to the `0x80010200` screen chunks in the .BUN bundles.

There is no table to read: the configs are constructed one `jal` at a time
inside `_GLOBAL_$I$*` functions scattered over a dozen object files.  So this
walks .text, finds every call to either constructor (or to Populate directly),
and linearly interprets the enclosing basic block far enough to recover the
argument registers -- lui/ori/addiu/move only, which is all gcc emits for
constant arguments.

Usage:
    python tools/screen_registry.py                 # the table
    python tools/screen_registry.py --json out.json
    python tools/screen_registry.py --check-port    # against the 3DS port
"""
import argparse
import json
import os
import re
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ELF = os.path.join(HERE, os.pardir, "PS2 Files", "NFSHP2.ELF")

CTOR4 = "__19FlailerScreenConfigPCcPF13ScreenMessageP18ScreenCallbackData_viPi"
CTOR7 = ("__19FlailerScreenConfigPCcPF13ScreenMessageP18ScreenCallbackData_"
         "vi12JoystickPortiT4Pi")
POPULATE = ("Populate__19FlailerScreenConfigPCcPF13ScreenMessageP18Screen"
            "CallbackData_vi12JoystickPortiT4Pi")

A1, A2, A3, T0, T1, T2, T3 = 5, 6, 7, 8, 9, 10, 11


class Elf:
    def __init__(self, path):
        self.data = open(path, "rb").read()
        d = self.data
        shoff, = struct.unpack_from("<I", d, 0x20)
        shentsize, shnum, shstrndx = struct.unpack_from("<HHH", d, 0x2E)
        raw = []
        for i in range(shnum):
            raw.append(struct.unpack_from("<IIIIII", d, shoff + i * shentsize))
        stroff = raw[shstrndx][4]
        self.secs = []
        for name, typ, flags, addr, off, size in raw:
            e = d.index(b"\0", stroff + name)
            self.secs.append((d[stroff + name:e].decode(), typ, addr, off, size))

    def read(self, addr, n):
        for _, typ, a, off, size in self.secs:
            if typ != 8 and a <= addr < a + size:
                return self.data[off + addr - a: off + addr - a + n]
        return None

    def cstr(self, addr, maxn=128):
        b = self.read(addr, maxn)
        if b is None:
            return None
        e = b.find(b"\0")
        s = b[:e if e >= 0 else maxn]
        try:
            s = s.decode("latin-1")
        except Exception:
            return None
        return s if s and all(32 <= ord(c) < 127 for c in s) else None

    def text(self):
        for name, typ, addr, off, size in self.secs:
            if name == ".text":
                return addr, self.data[off:off + size]
        raise SystemExit("no .text")


def symbols(elf_path):
    out = subprocess.run([sys.executable, os.path.join(HERE, "mipsdis.py"),
                          "--elf", elf_path, "--grep", "."],
                         capture_output=True, text=True).stdout
    syms = []
    for line in out.splitlines():
        m = re.match(r"([0-9a-f]{8})\s+(\d+)\s+(\S+)", line)
        if m:
            syms.append((int(m.group(1), 16), int(m.group(2)), m.group(3)))
    syms.sort()
    return syms


def sint(v):
    if v is None:
        return -1
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def writes(w):
    """The register this instruction defines, or None."""
    op = w >> 26
    fn = w & 0x3F
    rt = (w >> 16) & 31
    rd = (w >> 11) & 31
    if op == 0:                                   # SPECIAL
        if fn in (8,):                            # jr
            return None
        if fn == 9:                               # jalr
            return rd or 31
        return rd or None
    if op == 1:                                   # REGIMM: bltzal/bgezal link
        return 31 if ((w >> 16) & 0x1E) == 0x10 else None
    if op in (2, 4, 5, 6, 7, 0x14, 0x15, 0x16, 0x17):   # j / branches
        return None
    if op == 3:                                   # jal
        return 31
    if op in (0x28, 0x29, 0x2A, 0x2B, 0x2E, 0x2F, 0x38, 0x39,
              0x3D, 0x3E, 0x3F, 0x37, 0x1F):      # stores (and lq/sq)
        return None if op not in (0x37, 0x1F) else rt
    if op in (0x11, 0x31, 0x35, 0x3D, 0x39):      # COP1 / fp ld/st
        return None
    return rt or None


class Resolver:
    """Backward constant propagation over a straight run of instructions.

    gcc builds every constant argument with lui/ori/addiu/move out of the
    same basic block, so walking back from the call site to the first
    definition of each argument register is enough -- and unlike a forward
    sweep it survives the branches that a forward sweep has to give up on.
    """

    def __init__(self, code, base, elf, gp):
        self.code = code
        self.base = base
        self.elf = elf
        self.gp = gp
        self.skip = -1

    def word(self, i):
        return struct.unpack_from("<I", self.code, i)[0]

    def arg(self, reg, call):
        """Value of `reg` as the call at byte offset `call` sees it.

        The delay slot runs before the jump, so it counts as the last
        instruction of the argument setup -- and its own operands come from
        before the `jal`, which is why the call itself is skipped.
        """
        self.skip = call
        w = self.word(call + 4)
        if writes(w) == reg:
            return self.eval(w, call + 4, 0)
        return self.value(reg, call, 0)

    def value(self, reg, i, depth=0):
        """Value of `reg` just before instruction index `i` (byte offset)."""
        if reg == 0:
            return 0
        if depth > 8:
            return None
        saved = 16 <= reg <= 23 or reg == 30       # s0..s7, s8: survive a call
        j = i - 4
        limit = max(0, i - 4 * 96)
        while j >= limit:
            w = self.word(j)
            if j != self.skip:
                if (w >> 26) == 3 and not saved:   # a call clobbers a0..t9
                    return None
                if writes(w) == reg:
                    return self.eval(w, j, depth)
            j -= 4
        return None

    def eval(self, w, j, depth):
        op = w >> 26
        fn = w & 0x3F
        rs = (w >> 21) & 31
        rt = (w >> 16) & 31
        imm = w & 0xFFFF
        simm = imm - 0x10000 if imm & 0x8000 else imm
        if op == 0x0F:                                        # lui
            return (imm << 16) & 0xFFFFFFFF
        if op in (0x09, 0x19):                                # addiu / daddiu
            v = self.value(rs, j, depth + 1)
            return None if v is None else (v + simm) & 0xFFFFFFFF
        if op == 0x0D:                                        # ori
            v = self.value(rs, j, depth + 1)
            return None if v is None else (v | imm) & 0xFFFFFFFF
        if op == 0 and fn in (0x21, 0x2D, 0x25):              # addu/daddu/or
            if rt == 0:
                return self.value(rs, j, depth + 1)
            if rs == 0:
                return self.value(rt, j, depth + 1)
        if op == 0x23 and rs == 28:            # lw rt, imm(gp) -- a .sdata ptr
            b = self.elf.read(self.gp + simm, 4)
            return None if b is None else struct.unpack("<I", b)[0]
        return None



# ---------------------------------------------------------------------------
# The port
# ---------------------------------------------------------------------------
#
# `kScreens[]` in the port's main.c is this table, hand-written: one row per
# screen the flow can be asked to change to, joining the name the flow code
# uses to the hash of the Flailer screen chunk. Two things can go wrong with
# a hand-written copy, and neither shows up until someone walks the frontend
# on the emulator:
#
#   * a hash that disagrees with the ELF -- the screen is registered under
#     the right name and draws the wrong chunk, or none;
#   * a name the port's own code passes to bgf_change_to_screen() and the
#     table does not carry. ChangeToScreen clears pCurrent before it looks
#     the name up, so the flow ends with no screen at all: a black top
#     screen until BACK, and one line of trace.
#
# This finds both. Names the port can reach are taken as every string
# literal anywhere in its sources that the ELF registry also knows -- the
# flow's own ChangeToScreen calls, the Mode Selects' item tables and the
# Options pages all spell the name out, so a literal that matches a
# registered screen name is a name the port can arrive at.

DEFAULT_SOURCE = os.path.join(HERE, os.pardir, "3DS Files", "source")

# { "Name", HASH_OR_DEFINE, callback },  -- across line breaks
PORT_ROW = re.compile(r'\{\s*"([^"]+)"\s*,\s*([A-Za-z0-9_]+)\s*,'
                      r'\s*([A-Za-z0-9_]+)\s*\}')
PORT_DEFINE = re.compile(r'#define\s+([A-Z0-9_]+)\s+(0x[0-9a-fA-F]+)u?')
LITERAL = re.compile(r'"([^"\\]{3,40})"')


def read_sources(src):
    text = {}
    for name in sorted(os.listdir(src)):
        if name.endswith((".c", ".h")):
            with open(os.path.join(src, name), "r", errors="replace") as f:
                text[name] = f.read()
    return text


def check_port(rows, src):
    if not os.path.isdir(src):
        print(f"\nno port sources at {src}", file=sys.stderr)
        return 2
    text = read_sources(src)
    defines = {}
    for body in text.values():
        for name, val in PORT_DEFINE.findall(body):
            defines[name] = int(val, 16)

    main_c = text.get("main.c", "")
    start = main_c.find("kScreens[] = {")
    end = main_c.find("\n};", start) if start >= 0 else -1
    if end < 0:
        print("\nno kScreens[] in main.c", file=sys.stderr)
        return 2
    # Rows carry a trailing comment naming the ELF class, and it sits
    # between two of the fields the row regex wants next to each other.
    block = re.sub(r"//[^\n]*", "", main_c[start:end])

    port = []
    for name, hash_tok, cb in PORT_ROW.findall(block):
        if hash_tok.startswith("0x"):
            value = int(hash_tok.rstrip("uU"), 16)
        elif hash_tok in defines:
            value = defines[hash_tok]
        else:
            value = None
        port.append((name, hash_tok, value, cb))

    # name -> the hashes the ELF registers it with
    elf = {}
    for r in rows:
        elf.setdefault(r["name"], []).append(
            [s["hash"] for s in r["screens"]])
    elf = {n: sorted({h for hs in v for h in hs}) for n, v in elf.items()}

    bad = 0
    print("\n--- the port's kScreens[] against the ELF ---")
    w = max(len(n) for n, _, _, _ in port)
    for name, tok, value, cb in port:
        want = elf.get(name)
        if want is None:
            print(f"  {name:{w}s}  NOT A REGISTERED SCREEN NAME ON THE DISC")
            bad += 1
        elif value is None:
            print(f"  {name:{w}s}  cannot resolve {tok}")
            bad += 1
        elif value not in want:
            print(f"  {name:{w}s}  {value:08x} but the ELF says "
                  + " ".join(f"{h:08x}" for h in want))
            bad += 1
        else:
            kind = "plain" if cb.endswith("plain_screen_callback") else "ported"
            print(f"  {name:{w}s}  {value:08x}  ok, {kind}")

    # Everything the port names anywhere that the disc registers as a screen.
    named = set()
    for body in text.values():
        for lit in LITERAL.findall(body):
            if lit in elf:
                named.add(lit)
    missing = sorted(named - {n for n, _, _, _ in port})
    print(f"\n--- names the port can reach and does not register: "
          f"{len(missing)} ---")
    for name in missing:
        hs = " ".join(f"{h:08x}" for h in elf[name])
        print(f"  {name:{w}s}  {hs}")

    print(f"\n{len(port)} registered, {len(elf) - len(port)} of the disc's "
          f"{len(elf)} screens still to go")
    if bad:
        print(f"{bad} rows disagree with the ELF")
    return 1 if (bad or missing) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", default=DEFAULT_ELF)
    ap.add_argument("--json")
    ap.add_argument("--check-port", action="store_true",
                    help="diff the port's kScreens[] against this registry "
                         "and list every name the port can reach and has "
                         "not registered")
    ap.add_argument("--source", default=DEFAULT_SOURCE,
                    help="the port's source directory")
    args = ap.parse_args()

    elf = Elf(args.elf)
    syms = symbols(args.elf)
    byname = {n: a for a, s, n in syms}
    addrs = [a for a, s, n in syms]

    def owner(a):
        lo, hi = 0, len(addrs)
        while lo < hi:
            mid = (lo + hi) // 2
            if addrs[mid] <= a:
                lo = mid + 1
            else:
                hi = mid
        return syms[lo - 1] if lo else None

    want = {}
    for nm in (CTOR4, CTOR7, POPULATE):
        if nm in byname:
            want[byname[nm]] = nm

    base, code = elf.text()
    res = Resolver(code, base, elf, byname.get("_gp", 0))
    rows = []
    sites = 0
    for i in range(0, len(code) - 4, 4):
        w, = struct.unpack_from("<I", code, i)
        # `jal`, and `j` too: gcc tail-calls the LAST constructor in each
        # _GLOBAL_$I$ function, and 13 of the 64 registrations on this disc
        # are that tail call. Scanning only for `jal` loses the last screen
        # of every object file that registers more than one.
        if (w >> 26) not in (2, 3):
            continue
        tgt = ((base + i) & 0xF0000000) | ((w & 0x03FFFFFF) << 2)
        if tgt not in want:
            continue
        sites += 1
        # arguments are live at the delay slot, so read them from i + 4
        get = lambda r: res.arg(r, i)                 # noqa: E731
        name = elf.cstr(get(A1) or 0)
        cb = get(A2) or 0
        cbsym = owner(cb) if cb else None
        h0, h1 = get(A3), (None if want[tgt] == CTOR4 else get(T1))
        pairs = []
        if h0:
            pairs.append((h0 & 0xFFFFFFFF,
                          -1 if want[tgt] == CTOR4 else sint(get(T0))))
        if h1:
            pairs.append((h1 & 0xFFFFFFFF, sint(get(T2))))
        own = owner(base + i)
        rows.append({
            "site": base + i,
            "in": own[2] if own else "?",
            "name": name,
            "callback": cbsym[2] if (cbsym and cb) else None,
            "callback_addr": cb,
            "screens": [{"hash": h, "port": p} for h, p in pairs],
            "help": (get(T0) if want[tgt] == CTOR4 else get(T3)) or 0,
        })

    missed = [r for r in rows if not r["name"]]
    if missed:
        print(f"note: {len(missed)} of {sites} call sites did not resolve "
              f"a name: " + ", ".join(f"{r['site']:08x}" for r in missed),
              file=sys.stderr)
    rows = [r for r in rows if r["name"]]
    rows.sort(key=lambda r: (r["name"] or "").lower())

    if args.json:
        with open(args.json, "w") as f:
            json.dump(rows, f, indent=1)

    w1 = max((len(r["name"]) for r in rows), default=11)
    print(f"{'screen name':{w1}s}  {'hash':8s} port  callback")
    print("-" * (w1 + 40))
    for r in rows:
        if not r["screens"]:
            print(f"{r['name']:{w1}s}  {'--':8s}  --   {r['callback'] or '-'}")
        for j, s in enumerate(r["screens"]):
            nm = r["name"] if j == 0 else ""
            cb = (r["callback"] or "-") if j == 0 else ""
            print(f"{nm:{w1}s}  {s['hash']:08x} {s['port']:4d}  {cb}")
    print(f"\n{len(rows)} screen configs, "
          f"{sum(len(r['screens']) for r in rows)} flailer screens")

    if args.check_port:
        sys.exit(check_port(rows, args.source))


if __name__ == "__main__":
    main()
