# `.mdebug` stab-string type info

`NFSHP2.ELF`'s `.mdebug` section (MIPS ECOFF "symbolic debug" format,
~24.9MB) holds essentially the entire game's C++ type layout: every
struct/class, its exact size, every field's byte/bit offset, and every
method's mangled signature. This is decoded by `tools/mdebug_stabs_scan.py`
without needing a MIPS-aware GDB or ps2dev toolchain (neither is installed
on this machine) -- see the script's docstring and `HANDOFF.md` Session 2
for why that shortcut is safe to take here.

## Why this works

Proper ECOFF debug info is a binary record format (`HDRR` symbolic header
pointing at `FDR`/`PDR`/`SYMR`/aux tables) that needs exact, tested
structure-layout code to parse correctly -- getting field bit-packing wrong
would silently corrupt every struct offset recovered from it. But the local
string pool where ECOFF stores its symbol/type *names* uses the same plain
a.out/GDB stab string grammar as a conventional `.stabstr` section, stored
as ordinary NUL-terminated ASCII -- confirmed by running
plain `strings` on the raw ELF and seeing readable entries like
`DataEventSelectScreen:Tt1267=s16SelectedTreeType:1,0,32;...`. So instead of
implementing ECOFF's binary record tables, the scanner just regex-scans
`.mdebug`'s raw bytes for stab-shaped strings and decodes the well-known
`name:T?t?<typenum>=s<size><fields>;<methods>;` struct grammar directly out
of that text.

## Grammar cheat-sheet (for reading raw/undecoded entries)

- `name:T<n>=s<size>...` -- `name` is a struct/union/enum **tag**, type
  number `n`, `s`=struct/class (`u`=union), `<size>` in bytes.
- `name:Tt<n>=...` -- both a tag AND typedef alias share type number `n`
  (i.e. `typedef struct Foo { ... } Foo;`).
- Field entry: `fieldname:typenum,bitoffset,bitsize;`
- Method entry: `methodname::<encoded-return-and-args>;<mangled-name>;<visibility-flags>.;`
  (not decoded by the scanner -- read these manually; see
  <https://sourceware.org/gdb/onlinedocs/stabs/> for the full grammar,
  particularly the C++ member-function extensions.)
- Type number references (`typenum` above) point at other stab type
  definitions elsewhere in the same string (`1` is usually a predefined
  basic type like `int`); cross-reference against
  `docs/mdebug_raw_strings.txt` by grepping for `=<typenum>` /
  `^<typenum>=` patterns if a field's exact type needs pinning down.

## Tool output

- `docs/mdebug_raw_strings.txt` -- every harvested stab-like string,
  deduplicated with an occurrence count prefix (`[xN]`). Grep this first
  when hunting for something not covered by the struct decoder (functions,
  enums, simple typedefs, method bodies).
- `docs/mdebug_structs.txt` -- 1,432 decoded struct/class definitions:
  name, exact size, every field's type#/byte-offset/bit-size, plus each
  struct's raw (undecoded) method entries for manual reading.

Regenerate both with:

```bash
python tools/mdebug_stabs_scan.py "../PS2 Files/NFSHP2.ELF"
```

## Coverage confirmed so far

A quick survey of `docs/mdebug_structs.txt` found essentially every system
already named in `HANDOFF.md`/`TASKS.md`'s phase breakdown, e.g.:
`Car`, `CarState`, `CarController`, `CarDamage`, `CarDriver` (physics/sim,
Phase 4); `AICarController`, `AIDriver`, `AIAction*` (AI, Phase 4);
`tCop`, `tAICop`, `tCopManager`, `tPursuit`, `tRoadBlock`, `tSpikeStrip`,
`CopDriver`, `CopMover` (Hot Pursuit-specific cop/pursuit systems, Phase 4);
`Camera`, `CameraMover`, `DriveCameraMover`, `BumperCameraMover` (Phase 3);
`FrontendDatabase`, `NewMainMenu`, `PauseMenu`, `tHelpMenu`,
`DataEventSelectScreen`, `DataSelectTrackScreen` (frontend/menu screens,
Phase 2). Every phase's RE work now has concrete named types with exact
sizes/offsets to start from, instead of needing to be discovered from
scratch in Ghidra.
