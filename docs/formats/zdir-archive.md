# `ZDIR.BIN` / `ZZDATA.BIN` -- the HP2 CD archive

`ZZDATA.BIN` (286,326,784 bytes) is the whole game's asset payload laid out
as raw CD sectors. `ZDIR.BIN` (2,676 bytes) is its directory. There is no
per-entry filename: the directory stores a 32-bit hash of the path instead.

Everything below is recovered from `PS2 Files/NFSHP2.ELF`, which is *not*
stripped -- see `HANDOFF.md` sessions 1-3.

## Directory record

`ZDIR.BIN` is a flat array of the `DirectoryEntry` struct (12 bytes, taken
verbatim out of `docs/mdebug_structs.txt`), little-endian, no header:

| offset | type  | field  | meaning                                          |
|-------:|-------|--------|--------------------------------------------------|
| 0      | `u32` | `Hash` | `bStringHash()` of the uppercased CD-relative path |
| 4      | `u32` | `Fad`  | "frame address" -- CD sector index into `ZZDATA.BIN` |
| 8      | `u32` | `Size` | exact byte length (not sector-rounded)            |

2676 / 12 = **223 entries exactly**, no remainder and no header.

A record's byte range inside `ZZDATA.BIN` is `[Fad * 2048, Fad * 2048 + Size)`.
Sanity check across all 223 records: the highest `Fad * 2048 + Size` lands
1,884 bytes short of `ZZDATA.BIN`'s real length -- ordinary trailing sector
padding, so the mapping is exact.

Entries **0-64** are in explicit load order (boot-critical texture packs,
then every car's geometry). Entries **65-222** are sorted by uppercased path.
That ordering is what lets an unidentified entry be bracketed alphabetically
between its two named neighbours.

Three entries have `Size == 0` and share their `Fad` with the next entry:
`FRONTEND\FRONTA.BUN`, `GLOBAL\GLOBALA.BUN`, `GLOBAL\INGAMEA.BUN` and
`TRACKS\TRACKA12.BUN`. The `A`/`B` bundle pair is the engine's
"permanent + streamed" split; on this build the `A` half is empty.

## `bStringHash` -- the filename hash

From `bStringHash__FPCc` at `0x0023b280` (decompiled in
`docs/zdir_decompiled.c`):

```c
int bStringHash(const char *s) {
    int h = -1;
    while (*s) h = h * 33 + (unsigned char)*s++;
    return h;
}
```

A djb2 variant seeded with `0xFFFFFFFF` instead of 5381. There is also
`bStringHash(const char *, int seed)` (`0x0023b2c0`), the same loop with a
caller-supplied seed -- which makes the hash incremental, and that is what
`tools/bhash.py`'s meet-in-the-middle `crack()` exploits.

**Paths are uppercased before hashing.** The ELF's own literals are mixed
case (`sound\engine.ctb`, `NIS\%s.bin`, `Sound\Speech\%sBAN.pck`) but only
their uppercase forms hash to directory entries. Separators are backslashes
and paths are relative to the CD root.

Implementation: `tools/bhash.py` (`bhash()`, and `crack()` to brute-force a
name back out of a hash).

## Recovering the filenames

Four independent sources, in descending order of reliability:

1. **String literals in the ELF**, uppercased -- e.g. `GLOBAL\DYNTEX.BIN`.
2. **`printf` templates in the ELF** expanded over their parameter range --
   `TRACKS\TRACKB%d.BUN`, `MARKERS\MARKERS%d.BIN`, `GLOBAL\POSTRACEANIM%d.LZC`,
   `NIS\%s.bin`, `Sound\Speech\%sBAN.pck`.
3. **Build paths embedded in the assets themselves.** Most chunk files still
   carry the authoring-machine path they were built from, e.g.
   `..\Psx2\CD\CARS\4DR_SEDAN02\GEOMETRY.BIN`. Everything after `\CD\` is
   the CD-relative path, and it hash-verifies. This is what named all 30
   car geometry files and the NIS set.
4. **Files still present on the disc dump** -- `PS2 Files/IRX243/` holds the
   IOP modules by name, and their byte sizes match entries 81-91 exactly.

`tools/zdir_names.py` runs all four and writes `docs/zdir_names.txt`.

## Compression: `.LZC` is *not* JDLZ

Most `.BIN`/`.BUN` files ship twice -- once raw, once as a `.LZC`. The `.LZC`
is a `COMP` container, decompressed by `LZDecompress()` at `0x001aa460`
(`LZCompress.obj`). HP2 predates EA Black Box's JDLZ, so the `source/jdlz.c`
copied over from NFSU2-3DS was **not** applicable here and has been deleted;
there is no `jdlz`/`JDLZ` symbol anywhere in the ELF or `.MAP`. The runtime
decoder is now `3DS Files/source/lzc.c`.

Header (16 bytes, little-endian):

| offset | type  | meaning                              |
|-------:|-------|--------------------------------------|
| 0      | `u32` | magic `'COMP'` (`0x504d4f43`)        |
| 4      | `u16` | version, `0x1001` in every HP2 file  |
| 6      | `u16` | method; `1` = stored, else LZSS      |
| 8      | `u32` | uncompressed size                    |
| 12     | `u32` | total file size (header + payload)   |

Payload is LZSS driven by 16-bit control words read LSB-first:

* control bit `0` -> copy one literal byte.
* control bit `1` -> read `b0`, `b1`:
  `distance = ((b0 & 0xf0) << 4) | b1` (1..4095, backwards from the output
  cursor), `length = 3 + (b0 & 0x0f)` (3..18). Matches may overlap, so the
  copy has to be byte-at-a-time.

The shift register is loaded as `b0 | b1 << 8 | 0x10000`; the extra sentinel
bit at position 16 is how the engine knows 16 tokens have been consumed. It
unrolls 16 tokens at a time but drops to one token at a time once within
32 bytes of the payload end, so a short final group cannot overrun.

Implementation: `tools/lzdecompress.py`. Validated byte-exact against the
raw `.BIN`/`.BUN` twin for every compressed entry in the archive, including
the 15 MB `FRONTEND\FRONTB.BUN` and the 9 MB `TRACKS\TRACKB12.BUN`.

## Contents of this build

`PS2 Files/` is a **demo disc**: only track 12 is present
(`TRACKS\TRACKB12.BUN`), the jukebox is `JUKEBOXMDEMODISK.JBC` and speech is
`SOUND\SPEECH\DEMODISK*.PCK`. Expect the retail disc to have the same
directory format with many more entries.

Broad shape of the 223 entries:

| entries | what                                                        |
|--------:|-------------------------------------------------------------|
| 0-2     | boot texture packs (`GLOBAL\DYNTEX`, `GLOBAL\HUDTEX`, `CARS\TEXTURES`) |
| 3-4     | a frontend sample bank (header + body)                       |
| 5-64    | 30 car models: `CARS\<NAME>\GEOMETRY.BIN` (+ `DASHGEOM.BIN`) and their `.LZC` twins |
| 65-79   | frontend + global bundles, pre/post-race animations          |
| 80-92   | `HOTCHUNK.TAG`, `IRX243\*.IRX` IOP modules                   |
| 93-100  | `LANGUAGES\FE_*.BIN` string tables                           |
| 101-110 | `MARKERS\MARKERS%d.BIN` plus marker design notes (plain text) |
| 111-112 | `MOVIES\INTRO\EALOGO_EN.AVI`                                 |
| 113     | `NFS6.ICO` (PS2 memory-card icon; HP2 was project "NFS6")    |
| 114-131 | `NIS\NIS_*.BIN` / `.CAM` cutscene pairs                      |
| 132-148 | `PAL.TAG`, then 16 `REPLAY\*` demo-mode replays              |
| 149-217 | sound: `.MSB`/`.MSH` sample banks, `SOUND\ENGINE.CTB`/`.LTB`, jukebox, speech `.PCK` |
| 218-222 | track 12: texture packs, `TRACKA12.BUN`/`TRACKB12.BUN`/`.LZC` |

## Tools

```bash
python tools/zdir_extract.py "PS2 Files/ZDIR.BIN" "PS2 Files/ZZDATA.BIN" out/
```

Writes every entry plus a `manifest.csv`, using the recovered filename where
one is known and `<index>_<hash>.bin` otherwise, and transparently
decompresses `COMP` payloads with `--decompress`.

A name goes to the entry whose `Hash` it has, which is how the game finds a
file. The index in `docs/zdir_names*.txt` only records where the name was
found. Until 2026-10-21 the extractor named entries by that index. On a
different release's disc (a friend's had 397 entries, not 406), that put
files under each other's names, and the 3DS faulted reading
`GLOBAL\HUDTEX.BIN`. When the disc's directory differs from the list's,
the extractor now lists the names that aren't on it. It also refuses a
folder whose `manifest.csv` has a name that doesn't hash to its entry,
because that folder came from the old naming.
