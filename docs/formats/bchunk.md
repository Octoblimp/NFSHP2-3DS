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
| `0x00030200` | `LoaderFontInfo`          | |
| `0x80034000` | `LoaderSolidList`         | container -- meshes; the backbone of car/track geometry |
| `0x80034008` | `LoaderAnimations`        | container |
| `0x00034013` | `LoaderPositionMarkers`   | 32-byte records, 16-byte aligned start |
| `0x80034015` | `LoaderLightList`         | container |
| `0x80034020` | `LoaderCollisionVolumes`  | container |
| `0x00034026` | `LoaderSmokeables`        | |
| `0x00034030` | `LoaderBodyDamage`        | |
| `0x80034100` | `LoaderScenery`           | container |
| `0x00034121` | `LoaderTrackRoutes`       | Phase 3 task 24 |
| `0x80034147` | `LoaderTrackPath`         | container |
| `0x00034200` | `LoaderTrackGeometry`     | |
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
| `0x80035000` | `LoaderAcidFX`            | container -- particle/FX system |
| `0x80036000` | `LoaderEventManager`      | container |
| `0x00037010` | `LoaderNisInfo`           | 160-byte records; cutscene table |
| `0x80038000` | `LoaderSoundScape`        | container -- ambient sound zones |
| `0x00039000` | `LoaderLanguage`          | `LANGUAGES\FE_*.BIN` string tables |
| `0x00039100` | `LoaderDemoModeReplay`    | `REPLAY\*` attract-mode recordings |
| --           | `LoaderNull`              | slot 0, the no-op sentinel |

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
