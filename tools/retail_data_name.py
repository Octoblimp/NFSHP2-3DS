"""The demo's name for a retail data address, through retail_map.json's
data pairs (`retail_match.py --data-out`): the demo symbol the matching
demo address falls in, and the offset into it.

    python tools/retail_data_name.py 0x003311f8 gp-20344
"""
import json
import sys
from pathlib import Path

import mipsdis
import retaildis

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "PS2 Files" / "NFSHP2.ELF"


def main():
    m = json.load(open(ROOT / "out" / "retail_map.json"))
    to_demo = {r: d for d, r in m["data"]}
    demo = mipsdis.Elf(str(DEMO))
    for t in sys.argv[1:]:
        if t.startswith("gp"):
            a = (retaildis.GP + int(t[2:], 0)) & 0xFFFFFFFF
        else:
            a = int(t, 0)
        d = to_demo.get(a)
        if d is None:
            print("%08x  no demo address" % a)
            continue
        best = None
        for name, (sa, sz) in demo.syms.items():
            if sa <= d < sa + max(sz, 1):
                if best is None or sa > best[1]:
                    best = (name, sa)
        print("%08x  demo %08x  %s" % (
            a, d, "%s+%d" % (best[0], d - best[1]) if best else "?"))


if __name__ == "__main__":
    main()
