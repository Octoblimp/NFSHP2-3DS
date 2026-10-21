"""The "fall:" lines of a debug log ("FallLog 1", main.c's logFallStep),
each with the collision floor's height under the car from the track's
bundle: the topology's packed polygons (chunk 0x34132), as topology.c
reads them, walls left out.

    python tools/fall_trace.py BUNDLE LOG [--all]

Prints the steps round the first one whose centre is below the floor
(clearance under 0), or every step with --all. A clearance is the car's
centre (CarState Position, the centre of gravity) less the highest floor
under it; standing on its wheels a car's is about 0.45.
"""
import re
import struct
import sys

CELL = 8.0


def chunks(b, s, e):
    while s + 8 <= e:
        t, n = struct.unpack_from("<II", b, s)
        yield t, s + 8, s + 8 + n
        s += 8 + n


def find(b, s, e, want, out):
    for t, cs, ce in chunks(b, s, e):
        if t == want:
            out.append((cs, ce))
        elif t & 0x80000000:
            find(b, cs, ce, want, out)


def floors(b):
    """Each floor polygon as a list of (x, y, z), from 0x34132's 32-byte
    records: flags at +3 (2 a wall, 4 the z times 4, 16 a quad), ZBase at
    +4, x and y in eighths at +8 and +16, z in 256ths over ZBase at +24."""
    out = []
    found = []
    find(b, 0, len(b), 0x34132, found)
    for cs, ce in found:
        a = cs if (ce - cs) % 32 == 0 else (cs + 15) & ~15
        for i in range((ce - a) // 32):
            o = a + i * 32
            fl = b[o + 3]
            if fl & 2:
                continue
            zb, = struct.unpack_from("<h", b, o + 4)
            vx = struct.unpack_from("<4h", b, o + 8)
            vy = struct.unpack_from("<4h", b, o + 16)
            vz = struct.unpack_from("<4h", b, o + 24)
            k = 4 if fl & 16 else 3
            zs = [zb + v / 256.0 for v in vz[:k]]
            if fl & 4:
                zs = [z * 4 for z in zs]
            out.append([(vx[j] / 8.0, vy[j] / 8.0, zs[j]) for j in range(k)])
    return out


def index(polys):
    grid = {}
    for p in polys:
        x0 = int(min(v[0] for v in p) // CELL)
        x1 = int(max(v[0] for v in p) // CELL)
        y0 = int(min(v[1] for v in p) // CELL)
        y1 = int(max(v[1] for v in p) // CELL)
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                grid.setdefault((gx, gy), []).append(p)
    return grid


def inside(x, y, vs):
    c = False
    n = len(vs)
    for i in range(n):
        x1, y1, _ = vs[i]
        x2, y2, _ = vs[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                c = not c
    return c


def z_at(x, y, vs):
    (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = vs[:3]
    ux, uy, uz = x1 - x0, y1 - y0, z1 - z0
    wx, wy, wz = x2 - x0, y2 - y0, z2 - z0
    nx = uy * wz - uz * wy
    ny = uz * wx - ux * wz
    nz = ux * wy - uy * wx
    if abs(nz) < 1e-9:
        return None
    return z0 - (nx * (x - x0) + ny * (y - y0)) / nz


def floor_at(grid, x, y):
    best = None
    for p in grid.get((int(x // CELL), int(y // CELL)), ()):
        if inside(x, y, p):
            z = z_at(x, y, p)
            if z is not None and (best is None or best < z):
                best = z
    return best


LINE = re.compile(r"fall: (-?\d+) dt ([\d.]+) at (\S+) (\S+) (\S+) "
                  r"vel (\S+) (\S+) (\S+) .*? up (\S+) (\S+) (\S+) "
                  r"wheels (-?\d+); (.*)$")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    every = "--all" in sys.argv
    if len(args) != 2:
        sys.exit(__doc__)
    grid = index(floors(open(args[0], "rb").read()))
    rows = []
    for raw in open(args[1], encoding="utf-8", errors="replace"):
        m = LINE.search(raw)
        if not m:
            continue
        g = m.groups()
        x, y, z = float(g[2]), float(g[3]), float(g[4])
        f = floor_at(grid, x, y)
        rows.append((int(g[0]), float(g[1]), x, y, z, f,
                     float(g[7]), float(g[10]), int(g[11]), g[12]))
    if not rows:
        sys.exit("no fall: lines in " + args[1])
    first = next((i for i, r in enumerate(rows)
                  if r[5] is not None and r[4] - r[5] < 0), None)
    if every:
        pick = range(len(rows))
    elif first is None:
        print("%d steps, none below the floor" % len(rows))
        pick = range(max(0, len(rows) - 10), len(rows))
    else:
        print("%d steps; first below the floor: frame %d" %
              (len(rows), rows[first][0]))
        pick = range(max(0, first - 25), min(len(rows), first + 15))
    for i in pick:
        fr, dt, x, y, z, f, vz, upz, wh, rest = rows[i]
        clear = "  ---" if f is None else "%6.2f" % (z - f)
        print("%6d %.3f %8.1f %8.1f z %7.2f clear %s vz %6.2f up %5.2f "
              "w%d | %s" % (fr, dt, x, y, z, clear, vz, upz, wh, rest))


main()
