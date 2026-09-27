#!/usr/bin/env python3
r"""Infer where retail moved each class's fields, from the matched code.

retail_match.py pairs each demo function with its retail twin. A method
reaches its object's fields through `this`, which arrives in a0. So where a
demo method and its twin line up instruction for instruction but for the
displacements, a load or store off `this` in the demo at offset d that
lines up with one off `this` in retail at offset r says the field at d moved
to r. Each such pair is a vote for (class, d) -> r.

`this` is followed along the straight line of each body: a0 at entry, any
register a move copies it into, and nothing after that register is written
or a call clobbers it. Branches are not followed, so the odd vote is noise,
and the majority is what is printed.

The alignment is over retail_match's layout mask, which clears every load
and store displacement, so a field that moved still lines up.

The field names are the demo's, from docs/mdebug_structs.txt.

Usage:
    python tools/retail_layout.py                 # every class that moved
    python tools/retail_layout.py --class Car     # one class, every field
    python tools/retail_layout.py --out docs/retail_layout.txt
"""
import argparse
import difflib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import retail_match as rm

ROOT = Path(__file__).resolve().parent.parent
STRUCTS = ROOT / "docs" / "mdebug_structs.txt"

A0 = 4
# what a call may leave changed: at v0-t7, t8, t9 and ra
CLOBBERED = set(range(1, 16)) | {24, 25, 31}
WIDTH = {32: 1, 33: 2, 34: 4, 35: 4, 36: 1, 37: 2, 38: 4, 39: 4,
         40: 1, 41: 2, 42: 4, 43: 4, 44: 8, 45: 8, 46: 4, 47: 0,
         26: 8, 27: 8, 30: 16, 31: 16, 49: 4, 53: 8, 54: 16, 55: 8,
         57: 4, 61: 8, 62: 16, 63: 8}


def class_of(name):
    """The class a mangled method belongs to, or None."""
    m = re.match(r"^(?:_\$_|[^_].*?__|__)(\d+)([A-Za-z_]\w*)", name)
    if not m:
        return None
    n = int(m.group(1))
    c = m.group(2)
    return c[:n] if len(c) >= n else None


def this_accesses(words):
    """(index, displacement, opcode) of each load or store whose base holds
    this. A call clobbers the caller-saved registers once its delay slot
    has run, since the slot often loads the callee's a0."""
    this = {A0}
    out = []
    clobber_after = -1
    for k, w in enumerate(words):
        op = w >> 26
        rs = (w >> 21) & 31
        rt = (w >> 16) & 31
        dest = None
        if op in rm.LOADSTORE:
            if rs in this:
                d = w & 0xffff
                out.append((k, d - 0x10000 if d & 0x8000 else d, op))
            if op in rm.RT_WRITERS:
                dest = rt
        elif op == 0:
            funct = w & 63
            rd = (w >> 11) & 31
            if funct in (0x21, 0x2d, 0x25) and rt == 0 and rs in this:
                this.add(rd)                    # move rd, this
            elif funct == 0x09:                 # jalr
                clobber_after = k + 1
            elif funct not in rm.R_NO_DEST:
                dest = rd
        elif op == 3:                           # jal
            clobber_after = k + 1
        elif op in rm.RT_WRITERS:
            dest = rt
        elif op == 17 and rs in (0, 2):
            dest = rt
        elif op == 28:
            dest = (w >> 11) & 31
        if dest is not None:
            this.discard(dest)
        if k == clobber_after:
            this -= CLOBBERED
    return out


def parse_structs(path=STRUCTS):
    """class name -> {byte offset: field name}, and name -> size. Where a
    name has several records, the one with the most fields is kept."""
    head = re.compile(r"^struct/class (\w+) \(size=(\d+) bytes\)")
    field = re.compile(r"^    (\w+)\s+type#\d+\s+offset=(\d+)\s+bits=(\d+)")
    raw = re.compile(r"^    (\w+):")
    tail = re.compile(r",(\d+),(\d+);?$")
    out, sizes = {}, {}
    name = cur = pending = None

    def finish():
        if cur is not None and len(cur) >= len(out.get(name, {})):
            out[name] = cur

    for line in Path(path).read_text(encoding="latin-1").splitlines():
        m = head.match(line)
        if m:
            finish()
            name, cur, pending = m.group(1), {}, None
            sizes.setdefault(name, int(m.group(2)))
            continue
        if cur is None:
            continue
        m = field.match(line)
        if m:
            cur.setdefault(int(m.group(2)) // 8, m.group(1))
            pending = None
            continue
        m = raw.match(line)
        t = tail.search(line)
        if m and not t:
            pending = m.group(1)
        elif t and pending:
            cur.setdefault(int(t.group(1)) // 8, pending)
            pending = None
    finish()
    return out, sizes


def votes(m):
    """(class, demo offset) -> Counter of retail offsets."""
    d, r = m.demo, m.retail
    dl, rl = rm.layout_mask(d.masked), rm.layout_mask(r.masked)
    by = rm.names_at(d)
    out = defaultdict(Counter)
    for i, rs in m.placed().items():
        cls = None
        for n in by[d.funcs[i][0]]:
            cls = class_of(n)
            if cls:
                break
        if not cls:
            continue
        s, e = m.bounds[i]
        n = m.rsize.get(i, e - s)
        dacc = {k: (x, op) for k, x, op in this_accesses(d.text[s:e])}
        racc = {k: (x, op) for k, x, op in this_accesses(r.text[rs:rs + n])}
        if not dacc or not racc:
            continue
        sm = difflib.SequenceMatcher(None, dl[s:e], rl[rs:rs + n],
                                     autojunk=False)
        for a0, b0, size in sm.get_matching_blocks():
            if size < 2:
                continue
            for k in range(size):
                x = dacc.get(a0 + k)
                y = racc.get(b0 + k)
                if x and y and x[1] == y[1]:
                    out[(cls, x[0])][y[0]] += 1
    return out


def layouts(v):
    """class -> [(demo offset, retail offset, votes, total)], by offset."""
    out = defaultdict(list)
    for (cls, dofs), c in v.items():
        rofs, n = c.most_common(1)[0]
        out[cls].append((dofs, rofs, n, sum(c.values())))
    for cls in out:
        out[cls].sort()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--class", dest="cls", action="append", default=[])
    ap.add_argument("--out")
    ap.add_argument("--min-votes", type=int, default=2)
    a = ap.parse_args()

    demo = rm.Image(rm.DEMO)
    retail = rm.Image(rm.RETAIL)
    m = rm.Match(demo, retail)
    m.run()
    lay = layouts(votes(m))
    fields, sizes = parse_structs()

    lines = []
    moved = 0
    for cls in sorted(lay):
        rows = [t for t in lay[cls] if t[2] >= a.min_votes and t[0] >= 0]
        if not rows:
            continue
        shifted = [t for t in rows if t[0] != t[1]]
        if a.cls and cls not in a.cls:
            continue
        if not a.cls and not shifted:
            continue
        moved += bool(shifted)
        fs = fields.get(cls, {})
        lines.append("== %s  demo size %s  %d fields seen, %d moved"
                     % (cls, sizes.get(cls, "?"), len(rows), len(shifted)))
        prev = None
        for dofs, rofs, n, tot in rows:
            delta = rofs - dofs
            show = a.cls or delta != prev
            prev = delta
            if show:
                lines.append("   %5d -> %5d  %+5d  %3d/%-3d %s"
                             % (dofs, rofs, delta, n, tot, fs.get(dofs, "")))
    text = "\n".join(lines) + "\n"
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write("# demo field offset -> retail, by tools/retail_layout.py\n")
            f.write("# a row is printed where the shift changes; "
                    "votes/total, then the demo field\n")
            f.write(text)
        print("wrote %s: %d classes moved" % (a.out, moved))
    else:
        sys.stdout.write(text)
        print("%d classes moved" % moved)


if __name__ == "__main__":
    main()
