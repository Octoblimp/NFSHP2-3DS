#!/usr/bin/env python3
r"""Decode a Flailer UI chunk (`0x80010200`) -- bWare's menu/HUD system.

Every screen in the game, frontend and in-game HUD alike, is a tree of these:

    0x80010200  FlailerChunk              container, one per project
      0x00010213  FlailerProjectChunk       20 bytes
      0x80010201  (screen)                  container, one per screen
        0x00010203  FlailerScreenChunk        40 bytes
        0x00010210  FlailerBitmapChunk        120 bytes (retail 144)
        0x00010212  FlailerTextChunk          76 + MaxChars bytes (retail 100)

The payload of each leaf is the engine class verbatim -- the chunk sizes are
literally `sizeof()` as recorded in the `.mdebug` type info
(`docs/mdebug_structs.txt`), so nothing here is inferred from byte patterns.
All three object classes derive from `bNode`, whose `Next`/`Prev` occupy the
first 8 bytes and are meaningless on disc; `FlailerPostLoadFixup__Fv`
(`0x0013f2b8`) relinks them once the chunk is in memory.

Objects refer to everything else by `bStringHash` of a name: the texture in a
texture pack, the font, the screen to show, the object to clip against. Pass
`--elf` (or let it find `PS2 Files/NFSHP2.ELF`) and `--textures` to resolve
those hashes back into names.

The string inside a text chunk is only the authoring placeholder and is
routinely stale -- the main menu ships `'Speed'` where the game draws
`'World Racing'`. When `LanguageID` is set, the renderer calls
`GetTranslatedString(LanguageID)` and draws that instead, so this resolves
IDs against `LANGUAGES\FE_ENGLISH.BIN` (see `tools/language_dump.py`) and
prints the real text with the placeholder in `(was ...)`.

Usage:
    python tools/flailer_dump.py FRONTEND/FRONTB.BUN
    python tools/flailer_dump.py FRONTEND/FRONTB.BUN --screen NEW_MAIN_MENU
    python tools/flailer_dump.py GLOBAL/INGAMEB.BUN --json hud.json
    python tools/flailer_dump.py FRONTEND/FRONTB.BUN --stats
    python tools/flailer_dump.py FRONTB.BUN --lang LANGUAGES/FE_GERMAN.BIN
"""
import argparse
import json
import os
import re
import struct
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bhash import bhash

FLAILER = 0x80010200
SCREEN_CONTAINER = 0x80010201
PROJECT = 0x00010213
SCREEN = 0x00010203
BITMAP = 0x00010210
TEXT = 0x00010212

OBJECT_TYPE = {0: "NONE", 1: "TEXT", 2: "BITMAP", 3: "POINT", 4: "LINE", 5: "SCREEN"}

VISIBILITY = {0: "INVISIBLE", 1: "VISIBLE", 2: "PSX2_ONLY", 3: "XBOX_ONLY"}

# FlailerObjectRotation, the type of FlailerObjectChunk::AnimationMode.
ANIM_MODE = {0: "NONE", 1: "ROTATE_AROUND", 2: "ROTATE_CENTER", 3: "ROTATE_LEFT",
             4: "ROTATE_RIGHT", 5: "TRANSLATE_LEFT", 6: "TRANSLATE_RIGHT",
             7: "ANIMATE_LEFT", 8: "ANIMATE_RIGHT", 9: "SLIDE_UP",
             10: "TACH_GRADIENT"}

# FlailerTextChunk::FormatOptions. These are #defines, so they are not in the
# .mdebug type info -- only the seven Is*() predicates that read them are
# (IsCentered, IsLeftJustified, IsRightJustified, IsDarkBackground,
# IsToBeClipped, IsToBeWrapped, IsFixedWidthNumber). Declaration order is NOT
# bit order: every bit below is pinned by the real renderer,
# Render__16FlailerTextChunk (0x0013ff40 -- RenderFlailerText at 0x0013feb0 is
# a 144-byte wrapper around it), which does
#
#   0x01  pen.x -= GetScaledWidth()        -> right-justified
#   0x02  (never tested)                   -> left-justified, the default
#   0x04  pen.x -= GetScaledWidth() * 0.5  -> centered
#   0x08  call RenderDarkBackground
#   0x10  carried into the per-glyph quad builder -> clipping
#   0x20  the word-wrap path
#   0x40  tail-call RenderStringFixedWidth
#
# The data agrees: across the three bundles the median TopLeftX is 490 for
# 0x01, 172 for 0x02 and 365 for 0x04 on a 640-wide screen.
FORMAT_BITS = [(0x01, "right"), (0x02, "left"), (0x04, "centered"),
               (0x08, "darkbg"), (0x10, "clip"), (0x20, "wrap"),
               (0x40, "fixedwidth")]

NO_HASH = 0xFFFFFFFF


def walk(data, off, end, depth=0):
    """Yield (depth, offset, type, size) over a bChunk tree."""
    while off + 8 <= end:
        t, s = struct.unpack_from("<2I", data, off)
        if t == 0 and s == 0:
            off += 8
            continue
        if off + 8 + s > end:
            return
        yield depth, off, t, s
        if t & 0x80000000 or (t & 0xF0000000) == 0xB0000000:
            for x in walk(data, off + 8, off + 8 + s, depth + 1):
                yield x
        off += 8 + s


def find_flailers(data):
    return [(off, size) for _, off, t, size in walk(data, 0, len(data)) if t == FLAILER]


def cstr(buf):
    return buf.split(b"\0")[0].decode("latin-1")


# Retail's FlailerObjectChunk carries the object's own name, a char[24], at
# +16, and every field the demo has from +16 on sits 24 bytes later. The
# demo's +16 is ObjectType (1..5) and +17 Visible (0..3); retail has a name's
# first two letters there. Offsets below are the demo's, plus `shift`.
NAME_LEN = 24


def layout_shift(data, off):
    """0 for the demo's object layout, NAME_LEN for retail's."""
    if 1 <= data[off + 16] <= 5 and data[off + 17] <= 3:
        return 0
    return NAME_LEN


def read_object(data, off, size):
    """The FlailerObjectChunk part, shared by bitmaps and text."""
    o = {}
    sh = o["shift"] = layout_shift(data, off)
    o["name"] = cstr(data[off + 16:off + 16 + NAME_LEN]) if sh else ""
    o["name_hash"], o["group_hash"] = struct.unpack_from("<2I", data, off + 8)
    o["object_type"], o["visible"], o["z"], o["dirty"] = \
        struct.unpack_from("<4B", data, off + sh + 16)
    o["top_left_x"], o["top_left_y"], o["scale_x"], o["scale_y"] = \
        struct.unpack_from("<4f", data, off + sh + 24)
    o["rotation"], o["anim_mode"], o["render_on_poly"], o["clip_to_poly"] = \
        struct.unpack_from("<4I", data, off + sh + 40)
    del size
    return o


def read_bitmap(data, off, size):
    o = read_object(data, off, size)
    o["kind"] = "bitmap"
    off += o["shift"]
    o["texture_hash"] = struct.unpack_from("<I", data, off + 56)[0]
    o["gourad"] = [struct.unpack_from("<I", data, off + 64 + 4 * i)[0] for i in range(4)]
    o["state_flags"] = data[off + 80]
    o["uv"] = list(struct.unpack_from("<8f", data, off + 88))
    return o


def read_text(data, off, size):
    o = read_object(data, off, size)
    o["kind"] = "text"
    sh = o["shift"]
    o["font_hash"], o["max_chars"], o["format_options"], o["color"], o["language_id"] = \
        struct.unpack_from("<5I", data, off + sh + 56)
    o["string"] = cstr(data[off + sh + 76:off + size])
    return o


def read_screen(data, off):
    s = {}
    s["name_hash"], s["callback_hash"], s["help_menu_hash"], s["background_hash"] = \
        struct.unpack_from("<4I", data, off + 8)
    # The fourth short is FlailerScreenChunk::Visible, but nothing on disc
    # survives: LoaderFlailerChunk does `sh 1,0x1e(screen)` on every screen it
    # links, so they all start FLAILER_SCREEN_INVISIBLE(1) regardless of what
    # the exporter wrote (it writes 0x0040 for all 76 screens in this build).
    s["res_x"], s["res_y"], s["num_objects"], _visible = \
        struct.unpack_from("<4H", data, off + 24)
    return s


def parse(data, off, size):
    """One 0x80010200 chunk -> {project_hash, screens: [...]}."""
    project = {"name_hash": None, "screens": []}
    screen = None
    for depth, o, t, s in walk(data, off + 8, off + 8 + size):
        if t == PROJECT:
            project["name_hash"] = struct.unpack_from("<I", data, o + 16)[0]
        elif t == SCREEN:
            screen = read_screen(data, o + 8)
            screen["objects"] = []
            project["screens"].append(screen)
        elif t == BITMAP and screen is not None:
            screen["objects"].append(read_bitmap(data, o + 8, s))
        elif t == TEXT and screen is not None:
            screen["objects"].append(read_text(data, o + 8, s))
        del depth
    return project


# -- name resolution ---------------------------------------------------------

# Numbered objects are never spelled out: the frontend builds the name with
# bSPrintf and hashes the result, so the ELF holds `MENUITEM_%d` and the
# chunk holds sixteen unrelated-looking hashes. Expanding one integer
# conversion over a small range recovers all of them. 32 is generous --
# `FlailerMenu` itself stops looking at 16.
_FORMAT = re.compile(r"^([^%]*)%(0?[0-9]?)[di]([^%]*)$")


def _expand(s, limit=32):
    m = _FORMAT.match(s)
    if not m:
        return
    head, flag, tail = m.groups()
    for n in range(limit):
        if flag.startswith("0") and len(flag) > 1:
            body = str(n).rjust(int(flag[1:]), "0")
        elif flag:
            body = str(n).rjust(int(flag))
        else:
            body = str(n)
        yield head + body + tail


def elf_names(path):
    """Every printable run in the ELF, as {hash: name}. Screen, object, font
    and callback names are all string literals in the frontend code."""
    out = {}
    try:
        blob = Path(path).read_bytes()
    except OSError:
        return out
    for m in re.finditer(rb"[ -~]{3,64}", blob):
        s = m.group().decode("latin-1")
        for cand in (s, s.upper()):
            out.setdefault(bhash(cand), cand)
            for grown in _expand(cand):
                out.setdefault(bhash(grown), grown)
    return out


def find_language(explicit, files):
    r"""A `LANGUAGES\FE_*.BIN` to resolve LanguageIDs against."""
    if explicit:
        return explicit
    roots = [os.path.dirname(os.path.abspath(p)) for p in files]
    for root in roots:
        for _ in range(4):
            guess = os.path.join(root, "LANGUAGES", "FE_ENGLISH.BIN")
            if os.path.exists(guess):
                return guess
            root = os.path.dirname(root)
    return None


def texture_names(paths):
    """{hash: name} for every texture in every pack in the given files."""
    out = {}
    try:
        from texture_convert import find_packs, parse_pack, textures
    except ImportError:
        return out
    for p in paths:
        try:
            buf = Path(p).read_bytes()
        except OSError:
            continue
        for off, size in find_packs(buf):
            try:
                _, info, _ = parse_pack(buf, off, size)
            except Exception:
                continue
            for t in textures(info):
                out.setdefault(t["hash"], t["name"])
    return out


def fmt_hash(h, names):
    if h in (0, NO_HASH):
        return "-"
    n = names.get(h)
    return n if n else "%08x" % h


def fmt_flags(v):
    on = [n for b, n in FORMAT_BITS if v & b]
    rest = v & ~sum(b for b, _ in FORMAT_BITS)
    if rest:
        on.append("0x%x" % rest)
    return "|".join(on) if on else "-"


def fmt_color(c):
    return "%02x%02x%02x%02x" % (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF, c >> 24)


def print_project(proj, names, only=None):
    print("project %s -- %d screens" % (fmt_hash(proj["name_hash"], names),
                                        len(proj["screens"])))
    for s in proj["screens"]:
        sn = fmt_hash(s["name_hash"], names)
        if only and only.upper() not in sn.upper():
            continue
        print("\n  screen %s  %dx%d  %d objects"
              % (sn, s["res_x"], s["res_y"], s["num_objects"]))
        for f in ("callback_hash", "help_menu_hash", "background_hash"):
            h = s[f]
            if h not in (0, NO_HASH):
                print("    %-16s %s" % (f[:-5], fmt_hash(h, names)))
        for o in s["objects"]:
            extra = []
            if o["scale_x"] != 1.0 or o["scale_y"] != 1.0:
                extra.append("scale=%.3g,%.3g" % (o["scale_x"], o["scale_y"]))
            if o["rotation"]:
                extra.append("rot=%d" % o["rotation"])
            if o["anim_mode"]:
                extra.append("anim=%s" % ANIM_MODE.get(o["anim_mode"], o["anim_mode"]))
            if o["render_on_poly"] not in (0, NO_HASH):
                extra.append("on=%s" % fmt_hash(o["render_on_poly"], names))
            if o["clip_to_poly"] not in (0, NO_HASH):
                extra.append("clip=%s" % fmt_hash(o["clip_to_poly"], names))
            if o["visible"] != 1:
                extra.append(VISIBILITY.get(o["visible"], str(o["visible"])))
            if o["kind"] == "bitmap":
                extra.append("tex=%s" % fmt_hash(o["texture_hash"], names))
                if len(set(o["gourad"])) != 1 or o["gourad"][0] != 0x80808080:
                    extra.append("rgba=" + ",".join(fmt_color(c) for c in o["gourad"]))
                if o["state_flags"]:
                    extra.append("state=0x%02x" % o["state_flags"])
                if o["uv"] != [0, 0, 1, 0, 0, 1, 1, 1]:
                    extra.append("uv=" + ",".join("%.3g" % v for v in o["uv"]))
            else:
                extra.append("font=%s" % fmt_hash(o["font_hash"], names))
                extra.append("fmt=%s" % fmt_flags(o["format_options"]))
                if o["color"] != 0x80808080:
                    extra.append("rgba=%s" % fmt_color(o["color"]))
                if o["language_id"]:
                    extra.append("lang=%d" % o["language_id"])
                # The baked-in string is the authoring placeholder; whenever
                # LanguageID is set the renderer draws GetTranslatedString()
                # instead, so show that and keep the placeholder alongside.
                shown = o.get("text")
                if shown is not None and shown != o["string"]:
                    extra.append("%d> %r (was %r)"
                                 % (o["max_chars"], shown, o["string"]))
                else:
                    extra.append("%d> %r" % (o["max_chars"], o["string"]))
            print("    %-6s z=%-3d @%7.1f,%7.1f  %-22s %s"
                  % (OBJECT_TYPE.get(o["object_type"], o["object_type"]),
                     o["z"], o["top_left_x"], o["top_left_y"],
                     fmt_hash(o["name_hash"], names), "  ".join(extra)))


def print_stats(projects):
    c = Counter()
    fmts = Counter()
    anims = Counter()
    states = Counter()
    for proj in projects:
        for s in proj["screens"]:
            c["screens"] += 1
            c["res %dx%d" % (s["res_x"], s["res_y"])] += 1
            for o in s["objects"]:
                c[o["kind"]] += 1
                anims[ANIM_MODE.get(o["anim_mode"], o["anim_mode"])] += 1
                if o["kind"] == "text":
                    fmts[o["format_options"]] += 1
                else:
                    states[o["state_flags"]] += 1
    for k, v in c.most_common():
        print("%-24s %d" % (k, v))
    print("\nFormatOptions:")
    for k, v in sorted(fmts.items()):
        print("  0x%02x %-40s %d" % (k, fmt_flags(k), v))
    print("\nAnimationMode:")
    for k, v in anims.most_common():
        print("  %-16s %d" % (k, v))
    print("\nBitmap StateFlags:")
    for k, v in sorted(states.items()):
        print("  0x%02x %d" % (k, v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="a .BUN / .BIN carrying a 0x80010200 chunk")
    ap.add_argument("--elf", help="NFSHP2.ELF, for resolving name hashes")
    ap.add_argument("--textures", action="store_true",
                    help="also resolve texture hashes against packs in the same files")
    ap.add_argument("--screen", help="only print screens whose name contains this")
    ap.add_argument("--lang", help=r"LANGUAGES\FE_*.BIN for resolving "
                                   r"LanguageIDs (default: find FE_ENGLISH.BIN)")
    ap.add_argument("--no-lang", action="store_true",
                    help="don't resolve LanguageIDs, show the baked-in strings")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--json", help="write the whole tree here")
    a = ap.parse_args()

    elf = a.elf
    if elf is None:
        for guess in ("PS2 Files/NFSHP2.ELF", "../PS2 Files/NFSHP2.ELF"):
            if os.path.exists(guess):
                elf = guess
                break
    names = elf_names(elf) if elf else {}
    if a.textures:
        names.update(texture_names(a.files))

    strings = {}
    if not a.no_lang:
        langfile = find_language(a.lang, a.files)
        if langfile:
            try:
                from language_dump import load as load_language
                strings = load_language(langfile).by_id
            except (ImportError, OSError, ValueError) as exc:
                print("%s: %s" % (langfile, exc), file=sys.stderr)
        elif a.lang:
            print("no such language file: %s" % a.lang, file=sys.stderr)

    projects = []
    for path in a.files:
        data = Path(path).read_bytes()
        found = find_flailers(data)
        if not found:
            print("%s: no 0x80010200 chunk" % path, file=sys.stderr)
            continue
        for off, size in found:
            proj = parse(data, off, size)
            proj["file"] = path
            for s in proj["screens"]:
                for o in s["objects"]:
                    if o["kind"] == "text" and o["language_id"] in strings:
                        o["text"] = strings[o["language_id"]]
            projects.append(proj)
            if not a.stats and not a.json:
                print("== %s @0x%x ==" % (path, off))
                print_project(proj, names, a.screen)

    if a.stats:
        print_stats(projects)
    if a.json:
        for proj in projects:
            proj["name"] = fmt_hash(proj["name_hash"], names)
            for s in proj["screens"]:
                s["name"] = fmt_hash(s["name_hash"], names)
                for o in s["objects"]:
                    o["name"] = fmt_hash(o["name_hash"], names)
                    if o["kind"] == "bitmap":
                        o["texture"] = fmt_hash(o["texture_hash"], names)
                    else:
                        o["font"] = fmt_hash(o["font_hash"], names)
        Path(a.json).write_text(json.dumps(projects, indent=1), encoding="utf-8")
        print("wrote %s" % a.json)


if __name__ == "__main__":
    main()
