#!/usr/bin/env python3
"""The capture's files (3DS Files/source/capture.h) made readable.

    capture_view.py DIR [--out OUT] [--box X0,Y0,X1,Y1 ...]

DIR holds nfshp2_cap_colour.bmp, nfshp2_cap_depth.bmp, nfshp2_cap_ids.bmp
and nfshp2_cap_ids.txt, from a device's card or Azahar's sdmc folder. OUT
(DIR by default) gets:

  * cap_colour.png, the frame;
  * cap_depth.png, its depth, the nearest white and the cleared black, the
    rest stretched between the nearest and farthest drawn;
  * cap_ids.png, each numbered draw in a colour of its own, and what was
    not one of them (the HUD, the clear) dimmed from the frame;
  * with nfshp2_cap_lod0.bmp there, cap_lod0.png, the frame with every
    texture at its level 0, and cap_lod0_diff.png, how far each pixel of it
    is from the frame's, four times over.

Each --box (the top screen's pixels, 400 by 240, x0 and y0 in, x1 and y1
out) prints the draws that own its pixels, the most first, with their
legend lines and their textures' names.
"""

import argparse
import os
import re
import sys

import numpy as np
from PIL import Image


def read_bmp(path):
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.uint32)


def legend(path):
    draws, names = {}, {}
    if not os.path.exists(path):
        return draws, names
    with open(path, encoding="latin-1") as f:
        for line in f:
            line = line.rstrip("\n")
            m = re.match(r"tex (0x[0-9a-f]+) \(data (0x[0-9a-f]+|\(nil\)).*\) (\S+)$",
                         line)
            if m:
                names[m.group(1)] = m.group(3)
                names.setdefault("data " + m.group(2), m.group(3))
                continue
            m = re.match(r"(\d+) ", line)
            if m:
                draws[int(m.group(1))] = line
    return draws, names


def texture_name(line, names):
    m = re.search(r"tex (0x[0-9a-f]+|\(nil\)) \(data (0x[0-9a-f]+|\(nil\))", line)
    if not m:
        return "-"
    return names.get(m.group(1)) or names.get("data " + m.group(2)) or "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--out")
    ap.add_argument("--box", action="append", default=[])
    a = ap.parse_args()
    out = a.out or a.dir
    os.makedirs(out, exist_ok=True)

    colour = read_bmp(os.path.join(a.dir, "nfshp2_cap_colour.bmp"))
    depth = read_bmp(os.path.join(a.dir, "nfshp2_cap_depth.bmp"))
    ids = read_bmp(os.path.join(a.dir, "nfshp2_cap_ids.bmp"))
    draws, names = legend(os.path.join(a.dir, "nfshp2_cap_ids.txt"))

    Image.fromarray(colour.astype(np.uint8)).save(os.path.join(out, "cap_colour.png"))

    d = (depth[..., 0] << 16) | (depth[..., 1] << 8) | depth[..., 2]
    drawn = d > 0
    img = np.zeros(d.shape, dtype=np.float64)
    if drawn.any():
        lo, hi = float(d[drawn].min()), float(d[drawn].max())
        img[drawn] = 40.0 + 215.0 * (d[drawn] - lo) / max(1.0, hi - lo)
    Image.fromarray(img.astype(np.uint8)).save(os.path.join(out, "cap_depth.png"))

    num = ids[..., 0] | (ids[..., 1] << 8)
    isid = ids[..., 2] == 0x55
    rng = np.random.default_rng(7)
    pal = rng.integers(60, 256, size=(65536, 3), dtype=np.uint32)
    vis = (colour // 4).astype(np.uint32)
    vis[isid] = pal[num[isid]]
    Image.fromarray(vis.astype(np.uint8)).save(os.path.join(out, "cap_ids.png"))

    lod0_path = os.path.join(a.dir, "nfshp2_cap_lod0.bmp")
    if os.path.exists(lod0_path):
        lod0 = read_bmp(lod0_path)
        Image.fromarray(lod0.astype(np.uint8)).save(os.path.join(out, "cap_lod0.png"))
        diff = np.abs(lod0.astype(np.int32) - colour.astype(np.int32))
        Image.fromarray(np.minimum(diff * 4, 255).astype(np.uint8)).save(
            os.path.join(out, "cap_lod0_diff.png"))
        print("level 0 against the frame: mean %.2f, %d pixels off by more than 24"
              % (diff.mean(), int((diff.max(axis=2) > 24).sum())))

    print("%d numbered draws in the legend, %d of them seen; depth %s" % (
        len(draws), len(np.unique(num[isid])),
        "%06x to %06x" % (d[drawn].min(), d[drawn].max()) if drawn.any() else "none"))
    for box in a.box:
        x0, y0, x1, y1 = (int(v) for v in box.split(","))
        sub = num[y0:y1, x0:x1][isid[y0:y1, x0:x1]]
        total = (y1 - y0) * (x1 - x0)
        print("\nbox %d,%d to %d,%d: %d pixels, %d not numbered" % (
            x0, y0, x1, y1, total, total - sub.size))
        vals, counts = np.unique(sub, return_counts=True)
        for v, c in sorted(zip(vals, counts), key=lambda t: -t[1])[:25]:
            line = draws.get(int(v), "(not in the legend)")
            print("  %5d px  %-24s %s" % (c, texture_name(line, names), line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
