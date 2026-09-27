#!/usr/bin/env python3
r"""The retail image in mipsemu, called by the demo's names.

A checker's model is an image run as shipped. Until the retail disc came
that image was the demo's, NFSHP2.ELF, which keeps its symbols. The retail
ELF, SLES_507.31, is stripped, so retail_match.py pairs each demo function
with its retail twin and this module hands those pairs to mipsemu:

- **Names.** `RetailEmu().addr_of("LoaderTrackGeometry__FP6bChunk")` is
  retail's address, and `label` names a retail pc by the demo's name.
- **Code.** `e.code(0x00150660)` is the retail twin of a demo function
  address. An address inside a function maps by its offset, and only where
  the twin is `same`, where offsets agree.
- **Data.** `e.data(GP - 22472)` is where retail keeps a demo datum: by the
  data map (matched code's loads and stores, and strings found once on each
  side), else by the demo object that holds it, moved as a whole, else by
  a single vote that nothing contradicts. The data map wants two votes; one
  aligned `lui`/`addiu` pair is how LoadChunks alone names LoaderTable.
- **Fields.** `e.field("Car", 1960)` is retail's offset for a demo field,
  by retail_layout.py.

The plain `Emu` answers the same three calls with the address or offset it
is given, so a checker written with them runs either image unchanged:

    e = retail_model.emu(retail, ieee=True)
    table = e.data(LOADERS)

One matcher run takes about half a minute. Its result is cached in
out/retail_map.json, and rebuilt when either ELF or the matching tools
change.

    python tools/retail_model.py                       # build the cache
    python tools/retail_model.py --name LoadChunks__FP6bChunki
    python tools/retail_model.py --data 0x00323428
"""
import argparse
import bisect
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mipsdis import Elf                   # noqa: E402
from mipsemu import Emu, MipsError        # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
DEMO = ROOT / "PS2 Files" / "NFSHP2.ELF"
RETAIL = ROOT / "PS2 Files" / "Full Game" / "SLES_507.31"
CACHE = ROOT / "out" / "retail_map.json"
RETAIL_GP = 0x003358f0
# The demo's bMemCpy, which shares its address with a compiler marker, so
# mipsemu's stub_bware stubs it by address.
DEMO_BMEMCPY = 0x002380c8


def _stamp():
    h = hashlib.sha1()
    for p in (DEMO, RETAIL):
        st = p.stat()
        h.update(("%s %d %d" % (p.name, st.st_size, int(st.st_mtime))).encode())
    for p in ("retail_match.py", "retail_layout.py", "mdebug.py",
              "retail_model.py"):
        h.update((TOOLS / p).read_bytes())
    return h.hexdigest()


def _build():
    import retail_layout as rl
    import retail_match as rm
    demo = rm.Image(rm.DEMO)
    retail = rm.Image(rm.RETAIL)
    m = rm.Match(demo, retail)
    m.run()
    by = rm.names_at(demo)
    funcs = []
    for i, rs in m.placed().items():
        a = demo.funcs[i][0]
        s, e = m.bounds[i]
        for name in by[a]:
            funcs.append([name, a, 4 * (e - s), retail.text_addr + 4 * rs,
                          4 * m.rsize.get(i, e - s), m.kind(i)])
    dm = m.data_map()
    data = sorted([da, ra] for da, ra in dm.items())
    weak = sorted([da, next(iter(v))] for da, v in m.data_pairs().items()
                  if da not in dm and len(v) == 1)
    fields = {}
    for cls, rows in rl.layouts(rl.votes(m)).items():
        keep = [[d, r] for d, r, n, _t in rows if n >= 2 and d >= 0]
        if keep:
            fields[cls] = keep
    return {"stamp": _stamp(), "funcs": sorted(funcs), "data": data,
            "weak": weak, "fields": fields}


def load_map(rebuild=False):
    """The cached matcher result, rebuilt when it is stale."""
    stamp = _stamp()
    if not rebuild and CACHE.exists():
        try:
            m = json.loads(CACHE.read_text())
            if m.get("stamp") == stamp:
                return m
        except ValueError:
            pass
    m = _build()
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(m, separators=(",", ":")))
    return m


class RetailMap(object):
    """The demo -> retail maps, for code, data and fields."""

    def __init__(self, raw=None):
        raw = raw or load_map()
        self.demo = Elf(str(DEMO))
        # name -> (demo addr, demo size, retail addr, retail size, kind)
        self.funcs = {}
        self.by_demo = {}
        for name, da, dsz, ra, rsz, kind in raw["funcs"]:
            self.funcs[name] = (da, dsz, ra, rsz, kind)
            self.by_demo.setdefault(da, (da, dsz, ra, rsz, kind))
        self.demo_starts = sorted(self.by_demo)
        self.datamap = {da: ra for da, ra in raw["data"]}
        self.weak = {da: ra for da, ra in raw["weak"]}
        self.fields = {c: dict((d, r) for d, r in rows)
                       for c, rows in raw["fields"].items()}
        # the demo's data objects, to move an interior address with its object
        self.objects = sorted((a, max(sz, 1), n)
                              for n, (a, sz) in self.demo.syms.items()
                              if sz and not self._is_code(a))
        self.obj_starts = [o[0] for o in self.objects]

    def _is_code(self, a):
        for s in self.demo.secs:
            if s["flags"] & 4 and s["addr"] <= a < s["addr"] + s["size"]:
                return True
        return False

    def code(self, a):
        if a in self.by_demo:
            return self.by_demo[a][2]
        i = bisect.bisect_right(self.demo_starts, a) - 1
        if i >= 0:
            da, dsz, ra, _rsz, kind = self.by_demo[self.demo_starts[i]]
            if a < da + dsz:
                if kind != "same":
                    raise MipsError("demo 0x%08x is inside %s, which retail "
                                    "changed: no offset maps"
                                    % (a, self.demo.label(da)))
                return ra + (a - da)
        raise MipsError("demo code 0x%08x has no retail twin" % a)

    def data(self, a):
        if a in self.datamap:
            return self.datamap[a]
        i = bisect.bisect_right(self.obj_starts, a) - 1
        if i >= 0:
            base, size, name = self.objects[i]
            if a < base + size and base in self.datamap:
                return self.datamap[base] + (a - base)
        if a in self.weak:
            return self.weak[a]
        raise MipsError("demo datum 0x%08x has no retail twin" % a)

    def field(self, cls, off):
        rows = self.fields.get(cls)
        if rows is None or off not in rows:
            raise MipsError("no retail offset for %s+%d" % (cls, off))
        return rows[off]


class RetailElf(Elf):
    """SLES_507.31, with the demo's names at retail's addresses."""

    def __init__(self, rmap, path=RETAIL):
        Elf.__init__(self, str(path))
        for name, (_da, _dsz, ra, rsz, _k) in rmap.funcs.items():
            self.syms[name] = (ra, rsz)
        for base, size, name in rmap.objects:
            if base in rmap.datamap and name not in self.syms:
                self.syms[name] = (rmap.datamap[base], size)
        self.syms["_gp"] = (RETAIL_GP, 0)
        self.by_addr = {}
        for n, (v, sz) in self.syms.items():
            if self._better(v, n, sz):
                self.by_addr[v] = n
        self.sorted_syms = sorted((v, k) for k, (v, _s) in self.syms.items())


_MAP = None


def retail_map():
    global _MAP
    if _MAP is None:
        _MAP = RetailMap()
    return _MAP


class RetailEmu(Emu):
    """mipsemu on the retail image. See the module docstring."""

    retail = True

    def __init__(self, **kw):
        Emu.__init__(self, path=str(RETAIL), **kw)
        self.map = retail_map()
        self.elf = RetailElf(self.map)
        self.reg[28] = RETAIL_GP

    def code(self, a):
        return self.map.code(a)

    def data(self, a):
        return self.map.data(a)

    def field(self, cls, off):
        return self.map.field(cls, off)

    def stub_bware(self):
        # Emu.stub_bware stubs bMemCpy at the demo's address; move it.
        saved = Emu.stub
        moved = self.code(DEMO_BMEMCPY)

        def stub(self_, sym, fn):
            if sym == DEMO_BMEMCPY:
                sym = moved
            saved(self_, sym, fn)
        try:
            Emu.stub = stub
            Emu.stub_bware(self)
        finally:
            Emu.stub = saved


# The demo image answers the same calls with what it is given.
Emu.retail = False
Emu.code = lambda self, a: a
Emu.data = lambda self, a: a
Emu.field = lambda self, cls, off: off


def emu(retail=False, **kw):
    """The demo image, or the retail one."""
    return RetailEmu(**kw) if retail else Emu(**kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--name", action="append", default=[])
    ap.add_argument("--data", action="append", default=[])
    ap.add_argument("--code", action="append", default=[])
    a = ap.parse_args()
    raw = load_map(a.rebuild)
    m = RetailMap(raw)
    print("%s: %d names, %d data addresses (%d more on one vote), "
          "%d classes' fields"
          % (CACHE.relative_to(ROOT), len(m.funcs), len(m.datamap),
             len(m.weak), len(m.fields)))
    for n in a.name:
        f = m.funcs.get(n)
        print("%s: %s" % (n, "demo %08x -> retail %08x (%s)" % (f[0], f[2], f[4])
                          if f else "no twin"))
    for x in a.code:
        print("code %s -> %08x" % (x, m.code(int(x, 16))))
    for x in a.data:
        print("data %s -> %08x" % (x, m.data(int(x, 16))))


if __name__ == "__main__":
    main()
