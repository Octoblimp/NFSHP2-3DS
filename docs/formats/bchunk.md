# bWare chunks -- the container every HP2 asset is built from

Every `.BIN` / `.BUN` in `ZZDATA.BIN` (and, after `COMP` decompression, every
`.LZC`) is a flat sequence of chunks. There is no file header: the first
8 bytes are already the first chunk.

```c
struct bChunk {
    unsigned int Type;
    unsigned int Size;   /* payload only -- does NOT include these 8 bytes */
};
```

* `Size` is always a multiple of 16. The engine DMAs chunks straight to VU /
  GS memory, so everything is quadword-aligned; short payloads are padded
  with `0x11` filler bytes.
* **Bit 31 of `Type` marks a container**: its payload is itself a chunk
  sequence. Leaf chunks are owned by a `Loader*()` function.
* A `Type == 0, Size == 0` header is inter-chunk padding, not a terminator --
  keep walking past it to the next 8-byte-aligned chunk.

Walker: `tools/bchunk_dump.py` (`--stats` for a type histogram).

## The loader dispatch table

`LoadChunks(bChunk *c, int len)` at `0x0018f878` is a one-liner:

```c
TraverseChunks(c, (char *)c + len, LoaderTable, 0x1f);
```

so `LoaderTable` (`0x003081d0`, 124 bytes) is 31 `int (*)(bChunk *)` slots,
each of which opens by rejecting chunks that are not its own type:

```c
int LoaderNisInfo(bChunk *c) {
    if (c->Type != 0x37010) return 0;
    NisInfoTable = c + 1;
    NumNisInfos  = c->Size / 0xa0;    /* 160-byte records */
    return 1;
}
```

`UnloaderTable` (`0x00308250`) mirrors it. Reading the table and decoding the
`lui`/`ori` pair at the top of each target recovers the complete chunk-type
map straight out of the ELF -- no decompiler needed. Four slots are thunks
that forward to a C++ member function (`Loader__12CameraLoaderP6bChunk` and
friends), so the guard has to be chased one `jal` deeper.

Regenerate with:

```bash
python tools/chunk_loader_table.py "PS2 Files/NFSHP2.ELF"
```

## Chunk types

| type         | loader                    | notes |
|--------------|---------------------------|-------|
| `0xb0300001` | `LoaderTexturePack`       | GS texture pack; `*TEX*.BIN` files start with this |
| `0x80010200` | `LoaderFlailerChunk`      | container -- "Flailer" is bWare's UI/menu system (Phase 2) |
| `0x00015010` | `LoaderFontInfo`          | **the font chunk actually on disc** -- see below |
| `0x00030200` | `LoaderFontInfo`          | accepted and then ignored; never appears on this disc |
| `0x80034000` | `LoaderSolidList`         | container -- meshes; the backbone of car/track geometry |
| `0x80034008` | `LoaderAnimations`        | container |
| `0x00034013` | `LoaderPositionMarkers`   | 32-byte records, 16-byte aligned start |
| `0x80034015` | `LoaderLightList`         | container |
| `0x80034020` | `LoaderCollisionVolumes`  | container |
| `0x00034026` | `LoaderSmokeables`        | |
| `0x00034030` | `LoaderBodyDamage`        | |
| `0x80034100` | `LoaderScenery`           | container |
| `0x00034121` | `LoaderTrackRoutes`       | Phase 3 task 24; also takes `0x00034122` |
| `0x80034147` | `LoaderTrackPath`         | container |
| `0x00034200` | `LoaderTrackGeometry`     | also takes `0x00034201`, `0x00034146` and, through `TopologyTree::Loader`, `0x00034130`..`0x00034133` -- the tool reports the first two only; see below and `topology.md` |
| `0x00034202` | `LoaderSun`               | |
| `0x00034250` | `LoaderWeatherMan`        | |
| `0x00034301` | `LoaderCharacterInfo`     | |
| `0x80034405` | `LoaderCameras`           | container -- Phase 3 task 23 |
| `0x80034500` | `LoaderCops`              | container -- Phase 4 pursuit |
| `0x00034600` | `LoaderCarInfo`           | Phase 4 car data |
| `0x00034700` | `LoaderPhysPredict`       | |
| `0x00034800` | `LoaderHeliSheet`         | pursuit helicopter |
| `0x80034a00` | `LoaderEventTree`         | container |
| `0x00034b00` | `LoaderDifficultyInfo`    | |
| `0x80035000` | `LoaderAcidFX`            | container -- particle/FX system; also takes `0x80035010` and `0x00035021` |
| `0x80036000` | `LoaderEventManager`      | container |
| `0x00037010` | `LoaderNisInfo`           | 160-byte records; cutscene table |
| `0x80038000` | `LoaderSoundScape`        | container -- ambient sound zones |
| `0x00039000` | `LoaderLanguage`          | `LANGUAGES\FE_*.BIN` string tables |
| `0x00039100` | `LoaderDemoModeReplay`    | `REPLAY\*` attract-mode recordings |
| --           | `LoaderNull`              | slot 0, the no-op sentinel |

### A loader can accept more than one type

`tools/chunk_loader_table.py` used to stop at each loader's first
`lui`/`ori` pair, which quietly reported only one type per slot. It now
follows the value instead -- which register holds the `lw` of `chunk->Type`,
what each other register was loaded with, and where a branch actually
compares the two -- so every accepted type comes out. Three things had to be
modelled to get this right:

* the EE's **likely** branches (`beql`/`bnel`), which several guards use;
* the **thunk slots**, where `move a1,a0` puts the `bChunk *` in `a1` before
  the `jal`, so which register holds the chunk has to be carried into the
  callee;
* **block boundaries**. The code between a guard's branch and the `b` that
  ends its body runs only when that type matched, so it is rolled back before
  the next guard is read. Without that, `LoaderFontInfo`'s `addiu v0,zero,1`
  overwrites the `lui v0,0x0001` belonging to the next comparison and
  `0x00015010` reads out as `0x00000001`.

It still misses five types, all `LoaderTrackGeometry`'s (`0x00150660`),
for two reasons:

* **`0x00034146`, the position markers.** Its `lui` sits in the delay slot
  at `0x001506a0` and its `ori` at `0x001506ec`, after a `lw v1,4(a1)`
  (the size) that takes over the register holding the type. The rollback
  restores the constants but not which register holds the type, so by the
  time the compare comes the tool has lost track of it.
* **`0x00034130`..`0x00034133`, the topology's four chunks.** Once its own
  three guards fail, the loader tail-calls `TopologyTree::Loader`
  (`jal 0x0014fc78` at `0x00150754`, `a0` = `&TheTopologyTree`). The tool
  follows a `jal` only out of a loader that has matched nothing so far.

Fixing the rollback for the first broke `LoaderTrackPath`, so the tool was
left as it is. `topology.md` has the seven types from the listing.

The one that mattered: **fonts are `0x00015010`, not `0x00030200`.**
`LoaderFontInfo` takes `0x00030200` and returns 1 without doing anything --
a dead branch for a chunk that appears nowhere on this disc -- and only
`0x00015010` allocates a `Font` and parses it.

### `0x00015010` -- the font chunk

The chunk header *is* the first two fields of `tTTFontHeader`, so the payload
begins at `mHashID`:

| offset | field | |
|-------:|-------|---|
| -8 | `mChunkID` | the chunk `Type`, `0x00015010` |
| -4 | `mChunkSize` | the chunk `Size` |
| 0  | `mHashID` | `bStringHash` of the font name, e.g. `FONT_A` |
| 4  | `mNumGlyphs` | |
| 8  | `mNumKerningPairs` | |
| 12 | `mGlyph` | **byte offset from the chunk header**, always 28 |
| 16 | `mKerningPair` | byte offset, `28 + mNumGlyphs * 32` |

`mGlyph`/`mKerningPair` are `tTTGlyph *` / `tTTKerningPair *` in the type
info and hold file offsets on disc, which the loader relocates. `tTTGlyph` is
32 bytes -- `u16 mID`, `u16 mNumKerningPairs`, then the floats `mPosX`,
`mPosY`, `mWidth`, `mHeight`, `mAdvance`, `mOffset`, then `mKerningTable` --
and `tTTKerningPair` is 8. The arithmetic closes exactly on every font on
disc: `28 + glyphs*32 + pairs*8 == Size + 8`.

All ten fonts the Flailer text objects name live in the three UI bundles --
five in `FRONTEND\FRONTB.BUN` (`FONT_IMPACTSMALL`, `FONT_STATS`,
`FONT_IMPACTBIG`, `FONT_IMPACTNORMAL`, `FONT_EVENTNUMBERS`), three in
`GLOBAL\GLOBALB.BUN` (`FONT_A`, `BUTTONSOUT`, `FONT_HUD`) and three in
`GLOBAL\INGAMEB.BUN` (`FONT_GAUGE`, `FONT_IMPACTSMALL` again,
`FONT_POSITION`). That is 11 chunks for 10 hashes, and the size arithmetic
closes on all 11. Glyph counts run from 9 (`FONT_POSITION`, the
digits) to 128, and kerning from none to 10,932 pairs (`FONT_IMPACTBIG`).

`mHashID` is what `FindFont` matches, and each font's glyph sheet is a
texture of the same name in a texture pack -- `mPosX`/`mPosY`/`mWidth`/
`mHeight` are pixel coordinates into it. That texture is also how the names
above were recovered: a font chunk carries only the hash, and the pack in the
same bundle carries the string.

Fewer fonts ship than the count suggests. `FONT_IMPACTSMALL` is byte-identical
in `FRONTB.BUN` and `INGAMEB.BUN`, and `FONT_A` and `FONT_STATS` are
byte-identical past the hash word -- the same metrics under two names, drawn
from two different sheets. So: 11 chunks, 10 hashes, 9 distinct fonts.

### `mKerningTable` is an index, and two tables are uninitialised

`tTTGlyph.mKerningTable` is a **pair index** into the font's single kerning
array, not a byte offset like `mGlyph`/`mKerningPair` in the header. The runs
sit in glyph order and each glyph's value is the running total of the pairs
before it -- `FONT_A`'s first four glyphs read 0, 1, 18, 25 against counts of
1, 17, 7, 16. Verified on all 11 chunks.

`tTTKerningPair` is `{u32 mGlyph; f32 mXOffset;}` and `mGlyph` is the
*following* character, so a run hangs off the glyph that precedes it.

Two fonts declare pairs that no glyph claims: `FONT_EVENTNUMBERS` (10 glyphs,
50 pairs) and `FONT_POSITION` (9 glyphs, 84 pairs) have `mNumKerningPairs`
== 0 on every glyph. Those tables are not merely unused -- they are
`0xCDCDCDCD` from end to end, MSVC's debug fill for uninitialised heap, so
the authoring tool wrote out memory it never filled in. A reader that walks
`mNumKerningPairs` from the header instead of per glyph will read that
garbage as kerning; walking per glyph steps over it, which is what the engine
does and what the port does.

### The port

`3DS Files/source/bfont.c` is the handheld's reader and `tools/font_dump.py`
the Python one; `tools/bfont_check.py` builds the first for the host and
diffs every glyph's metrics and its summed kerning against the second. All 11
chunks agree, 953 lines, 0 differences.

## Sub-chunks inside a `SolidList` (`0x80034000`)

Observed in every car `GEOMETRY.BIN`. Each mesh is a `0x80034002` container:

| type         | typical size | role |
|--------------|-------------:|------|
| `0x00034003` | 192 or 204   | solid header/descriptor (bounding box, counts, name offset) |
| `0x00034004` | n * 16       | vertex/transform table |
| `0x00034005` | large        | packed VU1 geometry -- the actual draw data |
| `0x00034006` | 8..40        | small per-solid table |
| `0x0003401d` | 8..48        | small per-solid table |

The per-solid names live in the text region rather than at the head of
`0x00034003`; `strings` on a decompressed geometry file yields the solid
names directly (`BARCHETTA_DASH`, `911TURBO_CV`, `DRIVER_MALE01A`, ...),
matching the `%s_DASH`, `%s_BRAKELIGHT`, `%s_TIRE_FRONT_A` templates in the
ELF. Decoding `0x00034005`'s VU1 packet layout is Phase 3 task 21 and is not
done yet.
