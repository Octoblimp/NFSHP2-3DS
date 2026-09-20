#!/usr/bin/env python3
"""Harvest and decode stab-syntax type strings embedded in NFSHP2.ELF's
.mdebug section.

Background (see HANDOFF.md Session 1): NFSHP2.ELF's small ELF .stab section
only holds VU microcode line info. The real struct/class layouts and
function signatures live in .mdebug, a MIPS ECOFF ("SGI symbolic debug")
section, ~24.9MB. Properly parsing full ECOFF (HDRR/FDR/PDR/SYMR binary
record tables) needs a MIPS-aware toolchain (gdb's mdebugread.c, or
binutils' ecoff.c) that isn't installed on this machine, and hand-rolling an
exact binary-compatible parser risks subtly wrong bitfield/offset decoding
that would poison every struct layout downstream.

This script sidesteps that: the local/aux string pool inside .mdebug stores
its type descriptions using the *same plain-ASCII a.out/GDB stab string
grammar* as a conventional .stabstr section (confirmed -- `strings
NFSHP2.ELF` already surfaces readable entries like
`DataEventSelectScreen:Tt1267=s16SelectedTreeType:1,0,32;...`). So instead
of parsing ECOFF's binary record structure, this just scans .mdebug for
printable-ASCII, NUL-terminated runs that look like stab strings, and
decodes the common "named struct/class with fields" grammar
(`name:T?t?<typenum>=s<size><field>;<field>;...<method>;...;`) into a
readable field-offset listing. Method (C++ member function) encodings are
left as raw text -- decoding those fully needs a much larger chunk of GDB's
stabsread.c and has far lower payoff than the field/offset data for porting
purposes.

This is a best-effort text-pattern decoder, not a validated ECOFF reader:
treat its struct layouts as a strong starting point to cross-check against
Ghidra's own decompilation of accessor code, not as ground truth on its own.

Usage:
    python tools/mdebug_stabs_scan.py "../PS2 Files/NFSHP2.ELF"

Writes:
    docs/mdebug_raw_strings.txt   -- every harvested stab-like string, deduped, with counts
    docs/mdebug_structs.txt       -- decoded struct/class field layouts
"""
import re
import struct
import sys
from collections import Counter
from pathlib import Path


def read_elf_section(path, name):
    with open(path, "rb") as f:
        data = f.read()
    if data[0:4] != b"\x7fELF":
        raise SystemExit("not an ELF file: %s" % path)
    if data[4] != 1:
        raise SystemExit("expected 32-bit ELF")
    (e_shoff,) = struct.unpack_from("<I", data, 0x20)
    (e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from("<HHH", data, 0x2e)

    def section_header(idx):
        off = e_shoff + idx * e_shentsize
        (sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size,
         sh_link, sh_info, sh_addralign, sh_entsize) = struct.unpack_from(
            "<IIIIIIIIII", data, off)
        return dict(name=sh_name, offset=sh_offset, size=sh_size)

    shstr_hdr = section_header(e_shstrndx)
    shstrtab = data[shstr_hdr["offset"]:shstr_hdr["offset"] + shstr_hdr["size"]]

    def sh_name_str(off):
        end = shstrtab.index(b"\x00", off)
        return shstrtab[off:end].decode("ascii", "replace")

    for idx in range(e_shnum):
        hdr = section_header(idx)
        if sh_name_str(hdr["name"]) == name:
            return data[hdr["offset"]:hdr["offset"] + hdr["size"]]
    raise SystemExit("section %s not found" % name)


# Printable-ASCII run, NUL-terminated, that looks like a stab string: starts
# with an identifier (or '~' for destructors) and contains a stab-descriptor
# colon reasonably early on. This intentionally over-matches somewhat --
# false positives just show up as uninteresting lines in the raw dump.
STAB_LIKE = re.compile(
    rb"[A-Za-z_~][A-Za-z0-9_~<>, ]{0,80}:[a-zA-Z0-9(){}#=&*,;.:_0-9\[\] -]{4,}"
)

MIN_LEN = 8
CONT = b"\\"   # a split stab string ends in a backslash


# A stab string too long for the assembler's line limit is split across
# consecutive symbol entries, every piece but the last ending in a backslash
# and the next picking up mid-token. 10,318 of the 68,317 strings in this
# .mdebug are continuations, and a struct whose definition straddles one
# comes out silently truncated: RaceParameters stopped at CopStrength and
# lost Boost, PlayerSettings, OpponentStrength and five more fields that
# way. The pieces are adjacent in the pool, so joining them is just "keep
# taking the next NUL-terminated string while this one ends in a backslash".
MAX_CONTINUATIONS = 64


def _string_at(blob, start, cap=4000):
    """The NUL-terminated string at `start`, and the offset just past it."""
    end = blob.find(b"\x00", start)
    if end == -1:
        end = len(blob)
    end = min(end, start + cap)
    return blob[start:end], end + 1


def harvest_strings(blob):
    seen = Counter()
    for m in STAB_LIKE.finditer(blob):
        # Extend forward from the regex's conservative match to the actual
        # NUL terminator, so long type strings aren't truncated -- and then
        # keep going through any continuation pieces.
        full, nxt = _string_at(blob, m.start(), (m.end() - m.start()) + 4000)
        joins = 0
        while full.endswith(CONT) and joins < MAX_CONTINUATIONS:
            more, nxt = _string_at(blob, nxt)
            if not more:
                break
            full = full[:-1] + more
            joins += 1
        if len(full) < MIN_LEN:
            continue
        try:
            text = full.decode("ascii")
        except UnicodeDecodeError:
            continue
        seen[text] += 1
    return seen


# Splits a stab type-description string into top-level ";"-separated member
# entries, without being fooled by ';' characters nested inside a method's
# own encoded type (methods contain their own internal ';'-delimited parts).
# Approach: find every top-level "name:" or "name::" start position (an
# identifier immediately followed by 1-2 colons), then each entry runs from
# one start position to the next.
MEMBER_START = re.compile(r"[A-Za-z_~][A-Za-z0-9_~]*::?")


def split_members(body):
    starts = [m.start() for m in MEMBER_START.finditer(body)]
    entries = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(body)
        entry = body[s:e].rstrip(";")
        if entry:
            entries.append(entry)
    return entries


# A data member is "name:<type>,<bit offset>,<bit size>". <type> is usually a
# bare type number, but a member whose type is spelled out in place -- an
# array, most often -- carries the whole definition instead:
#
#   PlayerStartPosition:1024=ar1;0;1;10,480,16
#
# and that definition has its own ';' and ',' in it. Anchoring the offset and
# size to the END of the entry and letting the type run is what tells the two
# apart; requiring a bare number, as this did, silently filed every array
# field under "methods" and dropped it from the dump. RaceParameters lost
# PlayerStartPosition and sObjective that way, both of which StartQuickRace
# writes. Method entries are not at risk: they all use "::".
FIELD_RE = re.compile(
    r"^([A-Za-z_~][A-Za-z0-9_~]*):(\d+)(?:=.*)?,(\d+),(\d+)$", re.DOTALL
)
STRUCT_DEF_RE = re.compile(
    r"^([A-Za-z_~][A-Za-z0-9_~<>, ]*):(T?t?)(\d+)=([su])(\d+)(.*)$", re.DOTALL
)


def decode_struct(name, text):
    """text is everything after 'name:' for a Tt<n>=s<size>... entry."""
    m = STRUCT_DEF_RE.match(name + ":" + text)
    if not m:
        return None
    tagname, descr, typenum, kind, size, body = m.groups()
    entries = split_members(body)
    fields = []
    methods = []
    for entry in entries:
        fm = FIELD_RE.match(entry)
        if fm:
            fname, ftype, foff, fsize = fm.groups()
            fields.append((fname, int(ftype), int(foff), int(fsize)))
        else:
            methods.append(entry)
    return dict(
        name=tagname, typenum=int(typenum), kind="struct/class" if kind == "s" else "union",
        size=int(size), fields=fields, methods=methods,
    )


def format_struct(d):
    lines = []
    lines.append("%s %s (size=%d bytes) [type#%d]" % (d["kind"], d["name"], d["size"], d["typenum"]))
    for fname, ftype, foff, fsize in d["fields"]:
        lines.append("    %-28s type#%-6d offset=%-5d bits=%d" % (fname, ftype, foff, fsize))
    if d["methods"]:
        lines.append("    -- %d method entries (raw, not decoded) --" % len(d["methods"]))
        for meth in d["methods"]:
            lines.append("    %s" % meth)
    return "\n".join(lines)


def main():
    if len(sys.argv) != 2:
        print("usage: mdebug_stabs_scan.py <path to ELF>", file=sys.stderr)
        raise SystemExit(2)
    elf_path = sys.argv[1]
    mdebug = read_elf_section(elf_path, ".mdebug")
    print("Scanning .mdebug (%d bytes)..." % len(mdebug), file=sys.stderr)

    found = harvest_strings(mdebug)
    print("Harvested %d unique stab-like strings (%d total occurrences)" %
          (len(found), sum(found.values())), file=sys.stderr)

    docs_dir = Path(elf_path).resolve().parent.parent / "docs"
    if not docs_dir.exists():
        docs_dir = Path("docs")
    docs_dir.mkdir(exist_ok=True)

    raw_path = docs_dir / "mdebug_raw_strings.txt"
    with open(raw_path, "w", encoding="utf-8") as f:
        for text, count in sorted(found.items()):
            f.write("[x%d] %s\n" % (count, text))
    print("Wrote %s" % raw_path, file=sys.stderr)

    struct_path = docs_dir / "mdebug_structs.txt"
    decoded = []
    seen_names = set()
    for text in found:
        if ":" not in text:
            continue
        name, _, rest = text.partition(":")
        if not re.match(r"^T?t?\d+=[su]\d+", rest):
            continue
        d = decode_struct(name, rest)
        if d and d["name"] not in seen_names:
            seen_names.add(d["name"])
            decoded.append(d)

    decoded.sort(key=lambda d: d["name"])
    with open(struct_path, "w", encoding="utf-8") as f:
        for d in decoded:
            f.write(format_struct(d))
            f.write("\n\n")
    print("Decoded %d struct/class definitions -> %s" % (len(decoded), struct_path), file=sys.stderr)


if __name__ == "__main__":
    main()
