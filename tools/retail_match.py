#!/usr/bin/env python3
r"""Carry the demo ELF's symbols over to the stripped retail ELF.

`PS2 Files/NFSHP2.ELF` is the June 2002 demo disc's build and keeps its
.symtab and .mdebug. `PS2 Files/Full Game/SLES_507.31` is the PAL retail
build of August 2002 and keeps neither. Both come out of the same code base
and the same compiler, so most functions are the same instructions at a
different address.

The match runs in four passes:

1. **Masking.** Each .text word has its link-dependent bits cleared: a j or
   jal target, a lui's immediate, the offset of anything based on gp, and
   the low half that an addiu, ori, load or store adds to a register a lui
   set. Both images are masked as one stream with the same rules, and the
   lui state is dropped after every jr and j delay slot.
2. **Exact.** Each demo function's masked body is looked up in retail's
   masked stream. A body that occurs once is an anchor. One that occurs more
   than once is placed between its neighbouring anchors, in the demo's link
   order.
3. **Calls.** Every matched pair is walked side by side. Where both have a
   jal at the same index, the two targets are the same function, which
   names the retail functions whose own code changed.
4. **Gaps.** What is left between two known retail functions is split at
   its jr-ra returns and aligned against the demo functions left between
   the same two neighbours, scored by how many masked words agree.

The data follows from the matched code: an instruction pair that builds an
address in the demo builds the matching address in retail, and gp-relative
accesses map the same way.

The demo's functions are .symtab's plus the procedures only .mdebug lists
(tools/mdebug.py): each unit's own copy of an inline destructor or operator
delete, and the statics. Without them a demo body runs on through them.

`--audit` reads every demo address the port's sources cite and says what
retail made of each function: the same code, the same but for field and
stack offsets (`layout`), changed, or unmatched. docs/retail_audit.txt is
its output, and tools/retail_layout.py says where the offsets went.

Usage:
    python tools/retail_match.py                  # summary
    python tools/retail_match.py --out out/retail_syms.txt
    python tools/retail_match.py --audit docs/retail_audit.txt
    python tools/retail_match.py --name Render__13CarRenderInfoP5eView...
    python tools/retail_match.py --diff SetBoost__10PhysicsCarf
"""
import argparse
import bisect
import difflib
import re
import struct
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "PS2 Files" / "NFSHP2.ELF"
RETAIL = ROOT / "PS2 Files" / "Full Game" / "SLES_507.31"

GP_REG = 28

# I-type opcodes whose 16-bit immediate can be a relocation's low half.
LO_OPS = {8, 9, 13, 24, 25,                 # addi addiu ori daddi daddiu
          26, 27, 30, 31,                   # ldl ldr lq sq
          32, 33, 34, 35, 36, 37, 38, 39,   # lb lh lwl lw lbu lhu lwr lwu
          40, 41, 42, 43, 44, 45, 46, 47,   # sb sh swl sw sdl sdr swr cache
          49, 53, 54, 55, 57, 61, 62, 63}   # lwc1 ldc1 lqc2 ld swc1 sdc1 sqc2 sd
# I-type opcodes that write rt.
RT_WRITERS = {8, 9, 10, 11, 12, 13, 14, 15, 24, 25,
              26, 27, 30, 32, 33, 34, 35, 36, 37, 38, 39, 55}
R_NO_DEST = {0x08, 0x0c, 0x0d, 0x0f, 0x11, 0x13, 0x18, 0x19, 0x1a, 0x1b,
             0x1c, 0x1d, 0x1e, 0x1f}


class Image(object):
    def __init__(self, path):
        self.path = Path(path)
        self.data = d = self.path.read_bytes()
        shoff = struct.unpack_from("<I", d, 0x20)[0]
        shentsize, shnum, shstrndx = struct.unpack_from("<3H", d, 0x2e)
        raw = [struct.unpack_from("<10I", d, shoff + i * shentsize)
               for i in range(shnum)]
        strsec = raw[shstrndx]

        def cstr(off):
            return d[off:d.index(b"\0", off)].decode("latin-1")

        self.secs = {}
        self.sec_list = []
        for f in raw:
            s = dict(zip(("name", "type", "flags", "addr", "off", "size",
                          "link", "info", "align", "entsize"), f))
            s["name"] = cstr(strsec[4] + f[0])
            self.sec_list.append(s)
            if s["name"]:
                self.secs[s["name"]] = s
        self.funcs = []      # (addr, size, name), .text only
        self.objects = []    # (addr, size, name)
        for s in self.sec_list:
            if s["type"] != 2:
                continue
            strtab = self.sec_list[s["link"]]
            for i in range(s["size"] // 16):
                nameoff, val, size, info = struct.unpack_from(
                    "<3IB", d, s["off"] + i * 16)
                if not nameoff:
                    continue
                name = cstr(strtab["off"] + nameoff)
                kind = info & 15
                if kind == 2 and self.in_text(val):
                    self.funcs.append((val, size, name))
                elif kind == 1:
                    self.objects.append((val, size, name))
        if ".mdebug" in self.secs:
            self._add_procedures()
        self.funcs.sort()
        self.objects.sort()
        t = self.secs[".text"]
        self.text_addr = t["addr"]
        self.text = struct.unpack_from("<%dI" % (t["size"] // 4), d, t["off"])
        self.masked = mask_stream(self.text)

    def _add_procedures(self):
        """The procedures .symtab leaves out: each translation unit's own
        copy of an inline destructor or operator delete, and the statics.
        Without them a function's body runs on through whatever follows."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import mdebug
        have = {a for a, _s, _n in self.funcs}
        for a, name, _file, _static in mdebug.MDebug(self.path).procedures():
            if a not in have and self.in_text(a):
                self.funcs.append((a, 0, name))
                have.add(a)

    def in_text(self, a):
        t = self.secs[".text"]
        return t["addr"] <= a < t["addr"] + t["size"]

    def word(self, a):
        return self.text[(a - self.text_addr) // 4]

    def read(self, addr, n):
        for s in self.sec_list:
            if s["type"] == 8 or not (s["flags"] & 2):
                continue
            if s["addr"] <= addr < s["addr"] + s["size"]:
                o = s["off"] + addr - s["addr"]
                return self.data[o:o + n]
        return b""

    def section_of(self, a):
        for s in self.sec_list:
            if (s["flags"] & 2) and s["addr"] <= a < s["addr"] + s["size"]:
                return s["name"]
        return None


def mask_stream(words):
    out = []
    hi = [False] * 32
    reset_after = -1
    for i, w in enumerate(words):
        op = w >> 26
        rs = (w >> 21) & 31
        rt = (w >> 16) & 31
        m = w
        dest = None
        if op in (2, 3):
            m = w & 0xfc000000
            if op == 3:
                dest = 31
            else:
                reset_after = i + 1
        elif op == 15:
            m = w & 0xffff0000
            hi[rt] = True
            dest = -1                       # handled
        elif op in LO_OPS and (rs == GP_REG or hi[rs]):
            m = w & 0xffff0000
            if op in RT_WRITERS:
                dest = rt
        elif op == 0:
            funct = w & 63
            rd = (w >> 11) & 31
            if funct == 8:
                reset_after = i + 1
            elif funct in (0x21, 0x2d) and (hi[rs] or hi[(w >> 16) & 31]):
                hi[rd] = True               # addu/daddu of a lui'd base
                dest = -1
            elif funct not in R_NO_DEST:
                dest = rd
        elif op in RT_WRITERS:
            dest = rt
        elif op == 17 and rs in (0, 2):     # mfc1 cfc1
            dest = rt
        elif op == 18 and rs in (1, 2):     # qmfc2 cfc2
            dest = rt
        elif op == 28:                      # MMI
            dest = (w >> 11) & 31
        if dest is not None and dest >= 0:
            hi[dest] = False
        out.append(m)
        if i == reset_after:
            hi = [False] * 32
    return out


LOADSTORE = {26, 27, 30, 31} | set(range(32, 48)) | {49, 53, 54, 55, 57, 61, 62, 63}
SP_REG = 29


def layout_mask(masked):
    """`masked` less what a struct's layout decides: every load and store's
    displacement, and an addiu's immediate when it offsets the stack or
    takes a member's address (another register plus a constant). What is
    left differs only where the code does."""
    out = []
    for w in masked:
        op = w >> 26
        rs = (w >> 21) & 31
        rt = (w >> 16) & 31
        if op in LOADSTORE or (op == 9 and (SP_REG in (rs, rt) or
                                            (rs and rs != rt))):
            w &= 0xffff0000
        out.append(w)
    return out


def body_bounds(img, idx):
    """[start, end) word indices of demo function idx, trailing zeros cut."""
    a, _size, _n = img.funcs[idx]
    if idx + 1 < len(img.funcs):
        end = img.funcs[idx + 1][0]
    else:
        end = img.text_addr + 4 * len(img.text)
    s = (a - img.text_addr) // 4
    e = (end - img.text_addr) // 4
    while e > s + 1 and img.text[e - 1] == 0:
        e -= 1
    # keep the delay slot of a trailing jr ra
    if e < (end - img.text_addr) // 4 and img.text[e - 1] == 0x03e00008:
        e += 1
    return s, e


def unique_funcs(img):
    """Demo functions deduplicated by address (aliases share a body)."""
    seen = {}
    for i, (a, sz, n) in enumerate(img.funcs):
        if a in seen:
            continue
        seen[a] = i
    order = sorted(seen.values(), key=lambda i: img.funcs[i][0])
    return order


def names_at(img):
    by = defaultdict(list)
    for a, sz, n in img.funcs:
        by[a].append(n)
    return by


K = 6


def build_index(masked):
    idx = defaultdict(list)
    for i in range(len(masked) - K + 1):
        idx[tuple(masked[i:i + K])].append(i)
    return idx


def find_all(masked, index, body):
    if len(body) >= K:
        cands = index.get(tuple(body[:K]), ())
        return [i for i in cands if masked[i:i + len(body)] == body]
    # short bodies: scan (only a few hundred of these)
    out = []
    n = len(body)
    first = body[0]
    i = 0
    L = len(masked) - n + 1
    while True:
        try:
            i = masked.index(first, i, L)
        except ValueError:
            break
        if masked[i:i + n] == body:
            out.append(i)
        i += 1
    return out


def lis_filter(pairs):
    """Keep the longest chain increasing in both demo and retail order."""
    pairs = sorted(pairs)
    tails, tails_i, prev = [], [], [None] * len(pairs)
    for k, (_d, r) in enumerate(pairs):
        j = bisect.bisect_left(tails, r)
        if j == len(tails):
            tails.append(r)
            tails_i.append(k)
        else:
            tails[j] = r
            tails_i[j] = k
        prev[k] = tails_i[j - 1] if j else None
    keep = set()
    k = tails_i[-1] if tails_i else None
    while k is not None:
        keep.add(k)
        k = prev[k]
    return [pairs[k] for k in sorted(keep)]


class Match(object):
    """The demo -> retail placement of every demo function.

    Retail's .text is first cut into units by what retail alone shows: the
    target of every j and jal, every code pointer in data that is not part
    of a jump table, and every prologue that follows a return. The exact
    placements then add their own edges.

    `same` holds the exact placements, which never move once made.
    `derived` maps the others to a unit, and is rebuilt every round from
    weighted evidence: jal pairs, vtable slots, the strings and data each
    side uses, and the last gap alignment. Each unit goes to one demo
    function only.
    """

    def __init__(self, demo, retail):
        self.demo = demo
        self.retail = retail
        self.order = unique_funcs(demo)
        self.ordpos = {i: p for p, i in enumerate(self.order)}
        self.bounds = {i: body_bounds(demo, i) for i in self.order}
        self.d_start = {self.bounds[i][0]: i for i in self.order}
        self.same = {}
        self.derived = {}
        self.gapped = {}
        self.rsize = {}
        self.gp_d = find_gp(demo)
        self.gp_r = find_gp(retail)
        self.d_addr = self.addresses(demo, 0, len(demo.text), self.gp_d)
        self.r_addr = self.addresses(retail, 0, len(retail.text), self.gp_r)
        self.base_starts = self._retail_starts()
        self.strmap = string_map(demo, retail)
        self._ratio = {}
        self._pairs = {}
        self._votes = None
        self.crossed = 0
        self.vt_map = {}
        self.starts = sorted(self.base_starts)

    # ------------------------------------------------------------ helpers
    def placed(self):
        out = dict(self.derived)
        out.update(self.same)
        return out

    def kind(self, i):
        if i in self.same:
            return "same"
        if i in self.derived:
            return "changed"
        return "unplaced"

    def _retail_starts(self):
        r = self.retail
        n = len(r.text)
        out = {0}
        for w in r.text:
            if w >> 26 in (2, 3):
                t = (((w & 0x3ffffff) << 2) - r.text_addr) // 4
                if 0 <= t < n:
                    out.add(t)
        for s in r.sec_list:
            if not (s["flags"] & 2) or (s["flags"] & 4) or s["type"] == 8:
                continue
            ws = struct.unpack_from("<%dI" % (s["size"] // 4), r.data, s["off"])
            for k, w in enumerate(ws):
                if w & 3 or not r.in_text(w):
                    continue
                t = (w - r.text_addr) // 4
                lone = not ((k and r.in_text(ws[k - 1])) or
                            (k + 1 < len(ws) and r.in_text(ws[k + 1])))
                # a jump table's entries sit side by side; a table of
                # functions' entries point just past a return
                if lone or self._after_return(t) or \
                        (r.text[t] & 0xffff8000) == 0x27bd8000:
                    out.add(t)
        for a in self.r_addr:
            if a is not None and r.in_text(a) and not a & 3:
                out.add((a - r.text_addr) // 4)
        for k in range(n - 2):
            if r.text[k] == 0x03e00008:
                q = k + 2
                while q < n and r.text[q] == 0:
                    q += 1
                if q < n and (r.text[q] & 0xffff8000) == 0x27bd8000:
                    out.add(q)
        return out

    def _after_return(self, t):
        """Word t follows a jr or j and its delay slot, past any padding."""
        r = self.retail
        k = t - 1
        while k >= 0 and r.text[k] == 0 and t - k < 4:
            k -= 1
        # k is the delay slot (possibly a nop that the loop ate)
        for slot in (k, k + 1):
            j = slot - 1
            if 0 <= j < t:
                w = r.text[j]
                if w == 0x03e00008 or w >> 26 == 2:
                    return True
        return False

    def repartition(self):
        """Unit starts: retail's own, less those inside exact placements,
        plus each exact placement's start and end."""
        inner = []
        edges = set()
        for i, rs in self.same.items():
            s, e = self.bounds[i]
            inner.append((rs, rs + e - s))
            edges.add(rs)
            end = rs + e - s
            while end < len(self.retail.text) and self.retail.text[end] == 0:
                end += 1
            edges.add(end)
        inner.sort()
        lo = [a for a, _b in inner]
        keep = set(edges)
        for x in self.base_starts:
            j = bisect.bisect_right(lo, x) - 1
            if j >= 0 and inner[j][0] < x < inner[j][1]:
                continue
            keep.add(x)
        self.starts = sorted(keep)

    def unit(self, k):
        """The unit [start, end) that retail word k lies in."""
        j = bisect.bisect_right(self.starts, k) - 1
        s = self.starts[j] if j >= 0 else 0
        e = self.starts[j + 1] if j + 1 < len(self.starts) else len(self.retail.text)
        return s, s + self._trim(s, e)

    def _fits(self, i, rs):
        s, e = self.bounds[i]
        return (0 <= rs and rs + e - s <= len(self.retail.masked)
                and self.retail.masked[rs:rs + e - s] == self.demo.masked[s:e])

    def _trim(self, s, e):
        r = self.retail
        while e > s + 1 and r.text[e - 1] == 0:
            e -= 1
        if e < len(r.text) and r.text[e - 1] == 0x03e00008:
            e += 1
        return e - s

    def ratio(self, i, rs, n):
        key = (i, rs, n)
        q = self._ratio.get(key)
        if q is None:
            s, e = self.bounds[i]
            sm = difflib.SequenceMatcher(None, self.demo.masked[s:e],
                                         self.retail.masked[rs:rs + n],
                                         autojunk=False)
            q = self._ratio[key] = sm.ratio()
        return q

    def pairs(self, i, rs, n):
        """Aligned (demo word, retail word) index pairs."""
        s, e = self.bounds[i]
        if i in self.same:
            return [(s + k, rs + k) for k in range(e - s)]
        key = (i, rs, n)
        c = self._pairs.get(key)
        if c is None:
            sm = difflib.SequenceMatcher(None, self.demo.masked[s:e],
                                         self.retail.masked[rs:rs + n],
                                         autojunk=False)
            c = []
            for a0, b0, size in sm.get_matching_blocks():
                if size >= 4:
                    c.extend((s + a0 + k, rs + b0 + k) for k in range(size))
            self._pairs[key] = c
        return c

    def trusted(self):
        for i, rs in self.placed().items():
            if i in self.same:
                yield i, rs, 4.0
            else:
                n = self.rsize.get(i)
                if n and self.ratio(i, rs, n) >= 0.5:
                    yield i, rs, 1.0

    # ------------------------------------------------------------- exact
    def exact(self):
        d, r = self.demo, self.retail
        index = build_index(r.masked)
        self.cands = {}
        for i in self.order:
            s, e = self.bounds[i]
            self.cands[i] = find_all(r.masked, index, d.masked[s:e])
        claim = defaultdict(int)
        for i in self.order:
            if len(self.cands[i]) == 1:
                claim[self.cands[i][0]] += 1
        uniq = [(self.bounds[i][0], self.cands[i][0]) for i in self.order
                if len(self.cands[i]) == 1 and claim[self.cands[i][0]] == 1
                and self.bounds[i][1] - self.bounds[i][0] >= 4]
        chain = lis_filter(uniq)
        self.crossed = len(uniq) - len(chain)
        for ds, rs in chain:
            self.same[self.d_start[ds]] = rs
        self.extend()
        self.window()
        self.extend()

    def extend(self):
        """Place the exact neighbours of exact placements, in link order."""
        added = 0
        taken = set(self.placed().values())
        grew = True
        while grew:
            grew = False
            for p, i in enumerate(self.order):
                if i not in self.same:
                    continue
                rs = self.same[i]
                s, e = self.bounds[i]
                if p + 1 < len(self.order):
                    j = self.order[p + 1]
                    if j not in self.same:
                        end = rs + e - s
                        for pad in range(4):
                            x = end + pad
                            if (x not in taken or self.derived.get(j) == x) \
                                    and self._fits(j, x):
                                self._set_same(j, x, taken)
                                added += 1
                                grew = True
                                break
                            if x >= len(self.retail.text) or self.retail.text[x] != 0:
                                break
                if p > 0:
                    j = self.order[p - 1]
                    if j not in self.same:
                        sj, ej = self.bounds[j]
                        for pad in range(4):
                            x = rs - pad - (ej - sj)
                            if (x not in taken or self.derived.get(j) == x) \
                                    and self._fits(j, x):
                                self._set_same(j, x, taken)
                                added += 1
                                grew = True
                                break
                            if pad >= rs or self.retail.text[rs - pad - 1] != 0:
                                break
        return added

    def _set_same(self, j, x, taken):
        for k, v in list(self.derived.items()):
            if v == x and k != j:
                del self.derived[k]
        self.derived.pop(j, None)
        self.same[j] = x
        taken.add(x)

    def window(self):
        pl = self.placed()
        seq = sorted((self.ordpos[i], rs) for i, rs in pl.items())
        ao = [p for p, _ in seq]
        taken = set(pl.values())
        n = 0
        for i in self.order:
            if i in self.same or not self.cands.get(i):
                continue
            p = self.ordpos[i]
            j = bisect.bisect_left(ao, p)
            lo = seq[j - 1][1] if j else -1
            hi = seq[j][1] if j < len(seq) else 1 << 30
            inside = [x for x in self.cands[i] if lo < x < hi and x not in taken]
            if len(inside) == 1:
                self._set_same(i, inside[0], taken)
                n += 1
        return n

    # ---------------------------------------------------------- evidence
    def evidence(self):
        d, r = self.demo, self.retail
        ev = defaultdict(lambda: defaultdict(float))
        same_starts = set(self.same.values())
        for i, rs, w in self.trusted():
            n = self.rsize.get(i, 0)
            for dk, rk in self.pairs(i, rs, n):
                dw, rw = d.text[dk], r.text[rk]
                op = dw >> 26
                da, ra = self.d_addr[dk], self.r_addr[rk]
                if da is not None and ra is not None and                         d.in_text(da) and r.in_text(ra):
                    # a function's address built in code: a callback
                    dt = (da - d.text_addr) // 4
                    rt = (ra - r.text_addr) // 4
                elif op in (2, 3) and rw >> 26 == op:
                    dt = (((dw & 0x3ffffff) << 2) - d.text_addr) // 4
                    rt = (((rw & 0x3ffffff) << 2) - r.text_addr) // 4
                else:
                    continue
                j = self.d_start.get(dt)       # a j counts when it is a tail call
                if j is not None and j not in self.same and rt not in same_starts:
                    ev[j][rt] += w
        self._vtable_evidence(ev, same_starts)
        self._data_evidence(ev, same_starts)
        for i, rs in self.gapped.items():
            if i not in self.same:
                ev[i][rs] += 1.5
        return ev

    def _vtable_evidence(self, ev, same_starts):
        d, r = self.demo, self.retail
        votes = self.data_pairs()
        pl = self.placed()
        self.vt_map = {}
        dm = self.data_map()
        for addr, size, name in d.objects:
            if size < 4 or size > 0x10000:
                continue
            if addr in dm:
                ra = dm[addr]
            elif addr in votes and name.startswith("_vt$"):
                ra, nv = max(votes[addr].items(), key=lambda t: t[1])
                if nv < 2 and len(votes[addr]) > 1:
                    continue
            else:
                continue
            if name.startswith("_vt$"):
                self.vt_map[name] = ra
            dd = d.read(addr, size)
            rr = r.read(ra, size + 64)
            slots = []
            for o in range(0, len(dd) - 3, 4):
                dw = struct.unpack_from("<I", dd, o)[0]
                if d.in_text(dw):
                    j = self.d_start.get((dw - d.text_addr) // 4)
                    if j is not None:
                        slots.append((o, j))

            def rword(o):
                if 0 <= o and o + 4 <= len(rr):
                    return struct.unpack_from("<I", rr, o)[0]
                return None

            shift = {}
            for o, j in slots:
                if j not in pl:
                    continue
                want = r.text_addr + 4 * pl[j]
                for sh in sorted(range(-16, 17, 2), key=abs):
                    if rword(o + 4 * sh) == want:
                        shift[o] = sh
                        break
            known = sorted(shift)
            for o, j in slots:
                if j in self.same:
                    continue
                k = bisect.bisect_left(known, o)
                before = shift[known[k - 1]] if k else None
                after = shift[known[k]] if k < len(known) else None
                if before is not None and after is not None:
                    if before != after:
                        continue
                    sh, w = before, 2.0
                elif before is not None or after is not None:
                    sh, w = (before if before is not None else after), 1.0
                else:
                    sh, w = 0, 0.5
                rw = rword(o + 4 * sh)
                if rw is not None and r.in_text(rw):
                    t = (rw - r.text_addr) // 4
                    if t not in same_starts:
                        ev[j][t] += w

    def data_map(self):
        """demo data address -> retail, from string contents and votes."""
        dm = dict(self.strmap)
        for a, v in self.data_pairs().items():
            if a in dm:
                continue
            ra, n = max(v.items(), key=lambda t: t[1])
            if n >= 2 and n >= 0.8 * sum(v.values()):
                dm[a] = ra
        return dm

    def _data_evidence(self, ev, same_starts):
        """A datum one demo function uses and one retail unit uses."""
        dm = self.data_map()
        want = set(dm.values())
        r_refs = defaultdict(set)
        for k, a in enumerate(self.r_addr):
            if a in want:
                r_refs[a].add(k)
        d_users = defaultdict(set)
        s_of = {}
        for i in self.order:
            s, e = self.bounds[i]
            for k in range(s, e):
                a = self.d_addr[k]
                if a is not None and a in dm:
                    d_users[a].add(i)
        for a, users in d_users.items():
            if len(users) != 1:
                continue
            (i,) = users
            if i in self.same:
                continue
            ks = r_refs.get(dm[a])
            if not ks:
                continue
            units = set(self.unit(k)[0] for k in ks)
            if len(units) != 1:
                continue
            (u,) = units
            if u not in same_starts:
                ev[i][u] += 2.0 if a in self.strmap else 1.0
        del s_of

    def resolve(self, ev):
        items = []
        for j, c in ev.items():
            if j in self.same:
                continue
            tot = sum(c.values())
            for rt, w in c.items():
                if w >= 0.6 * tot and (w >= 1.5 or len(c) == 1):
                    items.append((w, -self.ordpos[j], j, rt))
        items.sort(reverse=True)
        taken = set(self.same.values())
        new = {}
        for w, _p, j, rt in items:
            if j in new or rt in taken:
                continue
            new[j] = rt
            taken.add(rt)
        changed = new != self.derived
        self.derived = new
        return changed

    def promote(self):
        n = 0
        taken = set(self.placed().values())
        for i, rs in list(self.derived.items()):
            if self._fits(i, rs):
                self._set_same(i, rs, taken)
                n += 1
        return n

    def sizes(self):
        self.repartition()
        pl = self.placed()
        claimed = set(pl.values())
        for i, rs in pl.items():
            s, e = self.bounds[i]
            if i in self.same:
                self.rsize[i] = e - s
            else:
                b = self._end_after(rs, claimed)
                self.rsize[i] = max(1, self._cut(i, rs, b) - rs)

    def _end_after(self, rs, claimed):
        """The first unit start past rs that another placement holds or
        that follows a return. A start that does neither is a stray code
        address inside the function, such as a constant that happens to
        fall in .text."""
        j = bisect.bisect_right(self.starts, rs)
        while j < len(self.starts):
            t = self.starts[j]
            if t in claimed or self._after_return(t):
                return t
            j += 1
        return len(self.retail.text)

    def _cut(self, i, rs, b):
        """End of placement i in retail: at the return that makes as many
        returns as the demo body has, once half the demo length is
        reached; otherwise the unit's end b."""
        s, e = self.bounds[i]
        d, r = self.demo, self.retail
        want = sum(1 for w in d.text[s:e] if w == 0x03e00008)
        if not want:
            return b
        seen = 0
        k = rs
        while k < b - 1:
            if r.text[k] == 0x03e00008:
                seen += 1
                if seen >= want and k + 2 - rs >= (e - s) // 2:
                    return min(b, k + 2)
            k += 1
        return b

    # -------------------------------------------------------------- gaps
    def gaps(self):
        # what the last alignment placed is aligned again, not built on,
        # so every round sees the same gaps
        pl = dict(self.same)
        for i, rs in self.derived.items():
            if self.gapped.get(i) != rs:
                pl[i] = rs
        seq = sorted((self.ordpos[i], rs, i) for i, rs in pl.items())
        new = {}
        for (p0, r0, i0), (p1, r1, _i1) in zip(seq, seq[1:]):
            if p1 - p0 < 2 or r1 <= r0:
                continue
            missing = self.order[p0 + 1:p1]
            gs = r0 + self.rsize.get(i0, 1)
            while gs < r1 and self.retail.text[gs] == 0:
                gs += 1
            if r1 <= gs:
                continue
            pieces = self._split(gs, r1)
            new.update(self._align(missing, pieces))
        changed = new != self.gapped
        self.gapped = new
        return changed

    def _split(self, s, e):
        """Units within [s, e), cut again at every return."""
        r = self.retail
        cuts = {s, e}
        j = bisect.bisect_right(self.starts, s)
        while j < len(self.starts) and self.starts[j] < e:
            cuts.add(self.starts[j])
            j += 1
        k = s
        while k < e:
            if r.text[k] == 0x03e00008 and k + 2 <= e:
                n = k + 2
                while n < e and r.text[n] == 0:
                    n += 1
                cuts.add(n)
                k = n
                continue
            k += 1
        cuts = sorted(c for c in cuts if s <= c <= e)
        return [(a, b) for a, b in zip(cuts, cuts[1:])
                if b > a and any(r.text[a:b])]

    def _score(self, i, a, b):
        s, e = self.bounds[i]
        x = self.demo.masked[s:e]
        y = self.retail.masked[a:b]
        if not x or not y:
            return 0.0
        cx = defaultdict(int)
        for w in x:
            cx[w] += 1
        common = 0
        for w in y:
            if cx[w] > 0:
                cx[w] -= 1
                common += 1
        return 2.0 * common / (len(x) + len(y))

    def _align(self, missing, pieces):
        """Order-keeping alignment of demo functions to runs of pieces.

        A banded dynamic programme: demo function a may only take pieces
        near a's proportional place in the gap, which keeps a gap of a few
        hundred functions affordable.
        """
        M, P = len(missing), len(pieces)
        if not M or not P or M * P > 400000:
            return {}
        band = max(40, P // 3)
        cnt = []
        for i in missing:
            s, e = self.bounds[i]
            c = defaultdict(int)
            for w in self.demo.masked[s:e]:
                c[w] += 1
            cnt.append((c, e - s))
        NEG = -1.0
        best = [[0.0] * (P + 1) for _ in range(M + 1)]
        back = [[None] * (P + 1) for _ in range(M + 1)]
        rm = self.retail.masked
        for a in range(M + 1):
            centre = a * P / float(M)
            for b in range(P + 1):
                if not a and not b:
                    continue
                opts = []
                if a:
                    opts.append((best[a - 1][b], ("d",)))
                if b:
                    opts.append((best[a][b - 1], ("p",)))
                if a and b and abs(b - centre) <= band:
                    cx, want = cnt[a - 1]
                    floor = 0.5 if want < 20 else 0.4
                    run = defaultdict(int)
                    common = 0
                    total = 0
                    for c in range(b - 1, max(-1, b - 9), -1):
                        lo, hi = pieces[c]
                        for w in rm[lo:hi]:
                            if run[w] < cx.get(w, 0):
                                common += 1
                            run[w] += 1
                        total += hi - lo
                        if total > 3 * want + 16:
                            break
                        sc = 2.0 * common / (want + total)
                        if sc >= floor:
                            opts.append((best[a - 1][c] + sc, ("m", c)))
                best[a][b], back[a][b] = max(opts, key=lambda t: t[0])
        del NEG
        out = {}
        a, b = M, P
        while a or b:
            op = back[a][b]
            if op[0] == "d":
                a -= 1
            elif op[0] == "p":
                b -= 1
            else:
                out[missing[a - 1]] = pieces[op[1]][0]
                a, b = a - 1, op[1]
        return out

    # --------------------------------------------------------------- run
    def run(self):
        self.exact()
        for _ in range(12):
            self.sizes()
            self._votes = None
            moved = self.resolve(self.evidence())
            moved |= bool(self.promote())
            moved |= bool(self.extend())
            self.sizes()
            moved |= self.gaps()
            self._votes = None
            moved |= self.resolve(self.evidence())
            moved |= bool(self.promote())
            moved |= bool(self.extend())
            self.sizes()
            if not moved:
                break
        self._votes = None

    # -------------------------------------------------------------- data
    def addresses(self, img, s, e, gp):
        """Per word of [s, e): the address a lui pair or gp builds, or None."""
        hi = {}
        out = []
        for k in range(s, e):
            w = img.text[k]
            op = w >> 26
            rs_ = (w >> 21) & 31
            rt = (w >> 16) & 31
            v = None
            if op == 15:
                hi[rt] = (w & 0xffff) << 16
            elif op in LO_OPS:
                lo = w & 0xffff
                if op == 13:
                    if rs_ in hi:
                        v = hi[rs_] | lo
                else:
                    if lo & 0x8000:
                        lo -= 0x10000
                    if rs_ == GP_REG and gp:
                        v = (gp + lo) & 0xffffffff
                    elif rs_ in hi:
                        v = (hi[rs_] + lo) & 0xffffffff
                if op in RT_WRITERS:
                    hi.pop(rt, None)
            elif op == 0 and (w & 63) in (0x21, 0x2d):
                rd = (w >> 11) & 31
                if rs_ in hi and rt not in hi:
                    hi[rd] = hi[rs_]
                elif rt in hi and rs_ not in hi:
                    hi[rd] = hi[rt]
                else:
                    hi.pop(rd, None)
            elif op == 0 and (w & 63) == 8:
                hi = {}
            elif op == 0 and (w & 63) not in R_NO_DEST:
                hi.pop((w >> 11) & 31, None)
            elif op == 3:
                hi.pop(31, None)
            out.append(v)
        return out

    def data_pairs(self):
        """demo data address -> {retail address: votes}, from trusted code."""
        if self._votes is not None:
            return self._votes
        votes = defaultdict(lambda: defaultdict(int))
        for i, rs, _w in self.trusted():
            n = self.rsize.get(i, 0)
            for dk, rk in self.pairs(i, rs, n):
                x, y = self.d_addr[dk], self.r_addr[rk]
                if x is not None and y is not None:
                    votes[x][y] += 1
        self._votes = votes
        return votes


def string_map(demo, retail):
    """demo string address -> retail, for contents unique on both sides."""
    def strings(img):
        out = defaultdict(list)
        for s in img.sec_list:
            if not (s["flags"] & 2) or (s["flags"] & 4) or s["type"] == 8:
                continue
            data = img.data[s["off"]:s["off"] + s["size"]]
            k = 0
            n = len(data)
            while k < n:
                c = data[k]
                if (k == 0 or data[k - 1] == 0) and 32 <= c < 127:
                    j = k
                    while j < n and (32 <= data[j] < 127 or data[j] in (9, 10, 13)):
                        j += 1
                    if j < n and data[j] == 0 and j - k >= 4:
                        out[bytes(data[k:j])].append(s["addr"] + k)
                    k = j + 1
                else:
                    k += 1
        return out
    a = strings(demo)
    b = strings(retail)
    return {a[t][0]: b[t][0] for t in a
            if len(a[t]) == 1 and len(b.get(t, ())) == 1}


def find_gp(img):
    """_gp from the entry code: `lui a0 ; addiu a0 ; move gp,a0`."""
    t = img.text
    val = {}
    for k in range(min(64, len(t))):
        w = t[k]
        op = w >> 26
        rs, rt = (w >> 21) & 31, (w >> 16) & 31
        if op == 15:
            val[rt] = (w & 0xffff) << 16
        elif op == 9 and rs in val:
            lo = w & 0xffff
            if lo & 0x8000:
                lo -= 0x10000
            val[rt] = (val[rs] + lo) & 0xffffffff
        elif op == 0 and (w & 63) in (0x21, 0x2d) and (w >> 11) & 31 == GP_REG:
            src = rs if rt == 0 else rt
            if src in val:
                return val[src]
    return None


def find(m, name, by):
    for i in m.order:
        if name in by[m.demo.funcs[i][0]]:
            return i
    return None


def diff(m, name, by):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import mipsdis
    d, r = m.demo, m.retail
    i = find(m, name, by)
    if i is None:
        print("%s: no such demo function" % name)
        return
    pl = m.placed()
    if i not in pl:
        print("%s: unplaced" % name)
        return
    rs = pl[i]
    s, e = m.bounds[i]
    n = m.rsize[i]
    print("--- %s  demo %08x  retail %08x  %s  ratio %.2f"
          % (name, d.funcs[i][0], r.text_addr + 4 * rs, m.kind(i),
             m.ratio(i, rs, n)))

    def dis(img, k):
        return mipsdis.decode(img.text[k], img.text_addr + 4 * k)[0]

    sm = difflib.SequenceMatcher(None, d.masked[s:e], r.masked[rs:rs + n],
                                 autojunk=False)
    for tag, a0, a1, b0, b1 in sm.get_opcodes():
        flag = " " if tag == "equal" else "*"
        for k in range(max(a1 - a0, b1 - b0)):
            x = dis(d, s + a0 + k) if a0 + k < a1 else ""
            y = dis(r, rs + b0 + k) if b0 + k < b1 else ""
            print("%s %08x %-34s | %08x %s"
                  % (flag, d.text_addr + 4 * (s + a0 + k) if x else 0, x,
                     r.text_addr + 4 * (rs + b0 + k) if y else 0, y))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", default=str(DEMO))
    ap.add_argument("--retail", default=str(RETAIL))
    ap.add_argument("--out")
    ap.add_argument("--data-out")
    ap.add_argument("--name", action="append", default=[])
    ap.add_argument("--diff", action="append", default=[],
                    help="print a placed function side by side")
    ap.add_argument("--audit", metavar="FILE",
                    help="write how retail treats each function the port cites")
    a = ap.parse_args()

    demo = Image(a.demo)
    retail = Image(a.retail)
    print("demo:   %d functions, .text %d words, gp %08x"
          % (len(demo.funcs), len(demo.text), find_gp(demo) or 0))
    print("retail: .text %d words, gp %08x"
          % (len(retail.text), find_gp(retail) or 0))
    m = Match(demo, retail)
    m.run()
    pl = m.placed()
    total = len(m.order)
    print("demo bodies %d: same %d, changed %d, unplaced %d; "
          "%d anchors crossed the link order"
          % (total, len(m.same), len(m.derived), total - len(pl), m.crossed))
    covered = sum(m.rsize.get(i, 0) for i in pl)
    print("retail .text covered: %d of %d words (%.1f%%)"
          % (covered, len(retail.text), 100.0 * covered / len(retail.text)))

    by = names_at(demo)
    for n in a.name:
        i = find(m, n, by)
        if i is None:
            print("%s: no such demo function" % n)
        elif i in pl:
            print("%s: demo %08x -> retail %08x (%s, %d words, ratio %.2f)"
                  % (n, demo.funcs[i][0], retail.text_addr + 4 * pl[i],
                     m.kind(i), m.rsize[i], m.ratio(i, pl[i], m.rsize[i])))
        else:
            print("%s: demo %08x -> unplaced" % (n, demo.funcs[i][0]))

    for n in a.diff:
        diff(m, n, by)

    if a.out:
        write_syms(m, by, a.out)
    if a.data_out:
        write_data(m, a.data_out)
    if a.audit:
        audit(m, by, a.audit)


PORT_SRC = ROOT / "3DS Files" / "source"


def cited(img):
    """demo function address -> the port's files that cite it."""
    starts = {a for a, _s, _n in img.funcs}
    out = defaultdict(set)
    for f in sorted(PORT_SRC.glob("*.[ch]")):
        for h in re.findall(r"0x(00[12][0-9a-fA-F]{5})\b",
                            f.read_text(encoding="latin-1")):
            a = int(h, 16)
            if a in starts:
                out[a].add(f.name)
    return out


def audit(m, by, path):
    """Each demo function the port cites, and what retail made of it.

    same     the same instructions
    layout   the same instructions but for field and stack offsets
    changed  the code differs; `code` is how much of it agrees once the
             offsets are set aside
    unplaced no retail function matched
    """
    d, r = m.demo, m.retail
    dl, rl = layout_mask(d.masked), layout_mask(r.masked)
    pl = m.placed()
    idx = {d.funcs[i][0]: i for i in m.order}
    rows = []
    for a, files in sorted(cited(d).items()):
        i = idx[a]
        s, e = m.bounds[i]
        k = m.kind(i)
        if i in pl:
            rs, n = pl[i], m.rsize[i]
            q = code = m.ratio(i, rs, n)
            if k == "changed":
                code = difflib.SequenceMatcher(None, dl[s:e], rl[rs:rs + n],
                                               autojunk=False).ratio()
                if dl[s:e] == rl[rs:rs + n]:
                    k = "layout"
            rows.append((k, a, 4 * (e - s), r.text_addr + 4 * rs, 4 * n,
                         q, code, by[a][0], files))
        else:
            rows.append((k, a, 4 * (e - s), 0, 0, 0.0, 0.0, by[a][0], files))
    count = defaultdict(int)
    for row in rows:
        count[row[0]] += 1
    summary = ("%d cited: %d same, %d layout, %d changed, %d unplaced"
               % (len(rows), count["same"], count["layout"],
                  count["changed"], count["unplaced"]))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# demo functions the port cites, and their retail twins,"
                " by tools/retail_match.py --audit\n")
        f.write("# %s\n" % summary)
        f.write("# kind     demo      dsize retail    rsize ratio code "
                "name  (files)\n")
        order = {"changed": 0, "unplaced": 1, "layout": 2, "same": 3}
        for k, a, dsz, ra, rsz, q, code, name, files in sorted(
                rows, key=lambda t: (order[t[0]], t[6], t[1])):
            f.write("%-8s %08x %6d %08x %6d %.2f  %.2f %s  (%s)\n"
                    % (k, a, dsz, ra, rsz, q, code, name,
                       " ".join(sorted(files))))
    print("wrote %s: %s" % (path, summary))


def write_syms(m, by, path):
    d, r = m.demo, m.retail
    pl = m.placed()
    rows = []
    for i in m.order:
        s, e = m.bounds[i]
        names = " = ".join(by[d.funcs[i][0]])
        if i in pl:
            n = m.rsize[i]
            rows.append((r.text_addr + 4 * pl[i], 4 * n, m.kind(i),
                         m.ratio(i, pl[i], n), d.funcs[i][0], 4 * (e - s), names))
    rows.sort()
    unplaced = [(d.funcs[i][0], 4 * (m.bounds[i][1] - m.bounds[i][0]),
                 " = ".join(by[d.funcs[i][0]])) for i in m.order if i not in pl]
    # retail code no demo function covers, cut at returns and call targets
    new = []
    cur = r.text_addr
    end = r.text_addr + 4 * len(r.text)
    for ra, rsz, *_ in rows + [(end, 0)]:
        if ra > cur:
            s = (cur - r.text_addr) // 4
            e = (ra - r.text_addr) // 4
            for a, b in m._split(s, e):
                if any(r.text[a:b]):
                    new.append((r.text_addr + 4 * a, 4 * (b - a)))
        cur = max(cur, ra + rsz)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# retail SLES_507.31 .text <- demo NFSHP2.ELF, by tools/retail_match.py\n")
        f.write("# retail   rsize kind     ratio demo      dsize name\n")
        for ra, rsz, k, q, da, dsz, names in rows:
            f.write("%08x %6d %-8s %.2f %08x %6d %s\n"
                    % (ra, rsz, k, q, da, dsz, names))
        f.write("# unplaced demo functions\n")
        for da, dsz, names in unplaced:
            f.write("-------- %6d %-8s %4s %08x %6d %s\n"
                    % (0, "unplaced", "-", da, dsz, names))
        f.write("# retail code no demo function covers\n")
        for ra, sz in new:
            f.write("%08x %6d new\n" % (ra, sz))
    print("wrote %s: %d placed, %d unplaced, %d new pieces (%d bytes)"
          % (path, len(rows), len(unplaced), len(new),
             sum(sz for _a, sz in new)))


def write_data(m, path):
    d = m.demo
    votes = m.data_pairs()
    objs = d.objects
    oaddr = [o[0] for o in objs]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("# demo data address -> retail, from matched code\n")
        f.write("# demo     retail    votes   of section  symbol\n")
        for da in sorted(votes):
            v = votes[da]
            ra, n = max(v.items(), key=lambda t: t[1])
            tot = sum(v.values())
            j = bisect.bisect_right(oaddr, da) - 1
            lab = ""
            if j >= 0 and objs[j][0] <= da < objs[j][0] + max(objs[j][1], 1):
                lab = objs[j][2] + ("" if da == objs[j][0]
                                    else "+0x%x" % (da - objs[j][0]))
            f.write("%08x %08x %5d %5d %-9s %s\n"
                    % (da, ra, n, tot, d.section_of(da) or "-", lab))
    print("wrote %s: %d demo data addresses" % (path, len(votes)))


if __name__ == "__main__":
    main()
