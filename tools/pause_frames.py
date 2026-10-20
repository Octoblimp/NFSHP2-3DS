#!/usr/bin/env python3
"""The pause's frames (3DS Files/source/capture.h) as pictures.

    pause_frames.py FILE [--out DIR] [--top N]

FILE is an nfshp2_pause_N.bin from the card: a race's last frames before a
pause, the top screen at half size (200 by 120), with "DebugLog 1". DIR
(FILE's name without .bin by default) gets:

  * frame_KK.png, each frame at twice its size, KK as the log's "pause
    frame KK" line numbers it;
  * sheet.png, every frame in rows of eight, each with its number and
    world time;
  * odd.png, the frames most unlike both of their neighbours, each between
    them.

A blink of a frame or two shows as a frame far from both neighbours while
they are near each other, so for each frame the score is how much further
it is from the two than they are from each other (the mean of each
pixel's largest RGB difference). The --top N (5 by default) highest are
printed with their world times, for the log's lines of those frames.
"""

import argparse
import os
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw


def read(path):
    data = open(path, "rb").read()
    if data[:8] != b"NFSHP2PF":
        sys.exit("%s: not a pause frames file" % path)
    version, count, w, h = struct.unpack_from("<4I", data, 8)
    if version != 1:
        sys.exit("%s: version %d, not 1" % (path, version))
    at = 24
    notes = []
    for _ in range(count):
        frame, world = struct.unpack_from("<If", data, at)
        notes.append((frame, world))
        at += 8
    size = w * h * 2
    frames = []
    for k in range(count):
        px = np.frombuffer(data, dtype="<u2", count=w * h, offset=at + k * size)
        # The buffer as the transfer engine wrote it: the screen on its
        # side, a row of the buffer a column of the screen from the bottom
        # up, the screen's left column first.
        buf = px.reshape(h, w)
        screen = buf[:, ::-1].T
        r = ((screen >> 11) & 0x1F).astype(np.uint8)
        g = ((screen >> 5) & 0x3F).astype(np.uint8)
        b = (screen & 0x1F).astype(np.uint8)
        rgb = np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4),
                        (b << 3) | (b >> 2)], axis=-1)
        frames.append(rgb)
    return notes, frames


def distance(a, b):
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=-1).mean())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file")
    ap.add_argument("--out")
    ap.add_argument("--top", type=int, default=5)
    a = ap.parse_args()
    notes, frames = read(a.file)
    out = a.out or os.path.splitext(a.file)[0]
    os.makedirs(out, exist_ok=True)
    n = len(frames)
    print("%d frames, world %.3f to %.3f s" % (n, notes[0][1], notes[-1][1]))

    for k, f in enumerate(frames):
        Image.fromarray(f).resize((f.shape[1] * 2, f.shape[0] * 2),
                                  Image.NEAREST).save(
            os.path.join(out, "frame_%02d.png" % k))

    fh, fw = frames[0].shape[:2]
    cols = 8
    rows = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * fw, rows * (fh + 12)), (0, 0, 0))
    d = ImageDraw.Draw(sheet)
    for k, f in enumerate(frames):
        x, y = (k % cols) * fw, (k // cols) * (fh + 12)
        sheet.paste(Image.fromarray(f), (x, y + 12))
        d.text((x + 2, y), "%d  %.3f" % (k, notes[k][1]), fill=(255, 255, 0))
    sheet.save(os.path.join(out, "sheet.png"))

    scores = []
    for k in range(1, n - 1):
        before, here, after = frames[k - 1], frames[k], frames[k + 1]
        s = (distance(here, before) + distance(here, after)) / 2 \
            - distance(before, after)
        scores.append((s, k))
    scores.sort(reverse=True)
    top = scores[:a.top]
    for s, k in top:
        print("frame %2d (frame %d, world %.3f s): %.1f further from its "
              "neighbours than they are from each other"
              % (k, notes[k][0], notes[k][1], s))
    if top:
        odd = Image.new("RGB", (3 * fw, len(top) * (fh + 12)), (0, 0, 0))
        d = ImageDraw.Draw(odd)
        for i, (s, k) in enumerate(top):
            y = i * (fh + 12)
            for j, m in enumerate((k - 1, k, k + 1)):
                odd.paste(Image.fromarray(frames[m]), (j * fw, y + 12))
            d.text((2, y), "%d-%d-%d  %.3f s  score %.1f"
                   % (k - 1, k, k + 1, notes[k][1], s), fill=(255, 255, 0))
        odd.save(os.path.join(out, "odd.png"))
    print("pictures in %s" % out)


if __name__ == "__main__":
    main()
