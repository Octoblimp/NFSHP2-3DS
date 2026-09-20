#!/usr/bin/env python3
r"""Check the 3DS C Flailer reader against tools/flailer_dump.py.

`3DS Files/source/bui.c` is the handheld's reader for the UI chunk. It
deliberately copies LoaderFlailerChunk's rule -- inside a screen, anything
that is not 0x00010203 is an object, identified afterwards by ObjectType --
whereas flailer_dump.py keys off the chunk id. The two agree only while the
chunk id and ObjectType agree, so this diff is also the check on that claim.

Usage:
    python tools/bui_check.py extracted/FRONTEND/FRONTB.BUN
    python tools/bui_check.py extracted/GLOBAL/*.BUN extracted/FRONTEND/*.BUN
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flailer_dump as fl                       # noqa: E402
import hostbuild                                # noqa: E402

SOURCES = ["tools/src/bui_test.c",
           "3DS Files/source/bui.c",
           "3DS Files/source/bchunk.c"]


def num(x):
    return "%g" % x


def py_lines(path):
    data = Path(path).read_bytes()
    found = fl.find_flailers(data)
    if not found:
        return []
    off, size = found[0]
    proj = fl.parse(data, off, size)
    screens = proj["screens"]
    total = sum(len(s["objects"]) for s in screens)
    out = ["project %08x %d %d" % (proj["name_hash"], len(screens), total)]
    for s in screens:
        out.append("screen %08x %d %d %d %d"
                   % (s["name_hash"], s["res_x"], s["res_y"],
                      s["num_objects"], len(s["objects"])))
        for o in s["objects"]:
            line = ("obj %d %d %d %08x %08x %s %s %s %s %d %d %08x %08x"
                    % (o["object_type"], o["visible"], o["z"], o["name_hash"],
                       o["group_hash"], num(o["top_left_x"]),
                       num(o["top_left_y"]), num(o["scale_x"]),
                       num(o["scale_y"]), o["rotation"], o["anim_mode"],
                       o["render_on_poly"], o["clip_to_poly"]))
            if o["kind"] == "bitmap":
                line += " tex %08x " % o["texture_hash"]
                line += " ".join("%08x" % c for c in o["gourad"])
                line += " " + " ".join(num(v) for v in o["uv"])
            else:
                line += (" txt %08x %d %08x %08x %d "
                         % (o["font_hash"], o["max_chars"],
                            o["format_options"], o["color"],
                            o["language_id"]))
                line += o["string"].encode("latin-1", "replace").hex()
            out.append(line)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--max-report", type=int, default=10)
    args = ap.parse_args()

    bad_total = 0
    with tempfile.TemporaryDirectory() as tmp:
        exe = hostbuild.build(tmp, SOURCES, "bui_test")
        for path in args.files:
            r = subprocess.run([str(exe), str(path)], capture_output=True,
                               text=True)
            if r.returncode:
                sys.stderr.write(r.stderr)
                sys.exit("bui_test failed on %s" % path)
            c = [x for x in r.stdout.split(chr(10)) if x.strip()]
            p = py_lines(path)
            bad = [(i, c[i] if i < len(c) else None,
                    p[i] if i < len(p) else None)
                   for i in range(max(len(c), len(p)))
                   if (c[i] if i < len(c) else None)
                   != (p[i] if i < len(p) else None)]
            print("%-34s %d lines, %d differ" % (Path(path).name, len(p),
                                                 len(bad)))
            for i, cv, pv in bad[:args.max_report]:
                print("  [%d] C=%r" % (i, cv))
                print("      py=%r" % (pv,))
            if len(bad) > args.max_report:
                print("  ... and %d more" % (len(bad) - args.max_report))
            bad_total += len(bad)
    return 1 if bad_total else 0


if __name__ == "__main__":
    sys.exit(main())
