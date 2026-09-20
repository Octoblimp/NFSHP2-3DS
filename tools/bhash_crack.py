"""Search for a bStringHash preimage: an object or texture name from its hash.

The bundles store `bStringHash(name)` and never the name, so every object in
a Flailer screen and every texture in a pack is a bare 32-bit number until
someone guesses the string. `tools/bhash.py` hashes a name you already have;
this goes the other way.

    python tools/bhash_crack.py 6eb9985d            # -> 'NONAME'
    python tools/bhash_crack.py --max 7 ab671c9a
    python tools/bhash_crack.py --words list.txt 70a404ec

**The hash splits, which is what makes this cheap.** bStringHash is
h = h * 33 + c seeded 0xFFFFFFFF, so for a name s = p + q with |q| = m:

    h(s) = h(p) * 33**m + H(q)          (mod 2**32)

where H is the same walk seeded 0. Tabulate H(q) for every suffix of length
m once, then one multiply and one lookup per prefix finds every hit --
meet in the middle, 37**4 + 37**4 work instead of 37**8.

**Know when the answer means anything.** The hash is 32 bits, so a sweep of
N candidate names throws up about N / 2**32 false preimages whatever the
tool does. Over [A-Z0-9_] that is:

    <= 5 chars    69M names     0.02 expected false hits -- decisive
    <= 6 chars    2.5G names    0.6                      -- decisive
    <= 7 chars    94G names     22                       -- eyeball them
    <= 8 chars    3.5T names    815                      -- meaningless

So the default stops at 6, `--max 7` is the last length worth reading, and
past that the only thing that works is a word list. Cracking these names is
dictionary-bound, not compute-bound: `NONAME` and `WHITEOUT_BAR` both fell
to a guess about what the object was *for*, not to a bigger sweep.
"""
import argparse
import sys

M = 1 << 32
ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"


def bhash(s, h=0xFFFFFFFF):
    """bStringHash__FPCc (0x0023b280). Seed 0 gives the H of the note above."""
    for c in s.encode("latin-1"):
        h = (h * 33 + c) & 0xFFFFFFFF
    return h


def _grow(level, alpha):
    """One more character on every string in {hash: [strings]}."""
    nxt = {}
    for hv, strings in level.items():
        base = (hv * 33) & 0xFFFFFFFF
        for c in alpha:
            key = (base + ord(c)) & 0xFFFFFFFF
            nxt.setdefault(key, []).extend(s + c for s in strings)
    return nxt


def sweep(targets, maxlen, alpha=ALPHA, out=sys.stdout):
    """Every name over `alpha` up to `maxlen` whose hash is in `targets`.

    A list per hash, not one string: H genuinely collides here. The alphabet
    spans more than 33 codes, so c * 33 + d aliases (c + 1) * 33 + (d - 33)
    -- 'AZ' and 'B9' land on the same H -- and keeping one suffix per key
    quietly drops two thirds of the space while still looking exhaustive.
    """
    m = min(4, maxlen)
    n = maxlen - m
    table = {0: [""]}
    for _ in range(m):
        table = _grow(table, alpha)
    p33 = pow(33, m, M)
    hits = 0
    level = {0xFFFFFFFF: [""]}
    for depth in range(n + 1):
        for hv, prefixes in level.items():
            want = (0 - hv * p33) & 0xFFFFFFFF
            for t in targets:
                suffixes = table.get((t + want) & 0xFFFFFFFF)
                if not suffixes:
                    continue
                for p in prefixes:
                    for q in suffixes:
                        print("%08x  %s" % (t, p + q), file=out)
                        hits += 1
        if depth < n:
            level = _grow(level, alpha)
    return hits


def from_words(targets, path, out=sys.stdout):
    """Hash every line of a word list. No length limit and no false hits."""
    hits = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            w = line.strip()
            if w and bhash(w) in targets:
                print("%08x  %s" % (bhash(w), w), file=out)
                hits += 1
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hashes", nargs="+", help="target hashes, hex")
    ap.add_argument("--max", type=int, default=6,
                    help="longest name to sweep (default 6; see the note in "
                         "this file about what lengths still mean anything)")
    ap.add_argument("--alphabet", default=ALPHA)
    ap.add_argument("--words", help="hash a word list instead of sweeping")
    a = ap.parse_args()

    targets = set()
    for h in a.hashes:
        targets.add(int(h, 16) & 0xFFFFFFFF)

    if a.words:
        hits = from_words(targets, a.words)
    else:
        if a.max > 7:
            print("warning: a sweep past 7 characters returns more false "
                  "preimages than real ones -- use --words", file=sys.stderr)
        hits = sweep(targets, a.max, a.alphabet)
    print("%d name%s" % (hits, "" if hits == 1 else "s"), file=sys.stderr)


if __name__ == "__main__":
    main()
