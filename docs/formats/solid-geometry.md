# `0x80034000` -- bWare eSolid geometry

Every piece of drawable geometry in the game -- cars, track scenery, the
frontend's mini track maps, the character models -- is an *eSolid* inside a
*solid list*. `CARS\*\GEOMETRY.BIN` and `CARS\*\DASHGEOM.BIN` hold one list
each, and the big bundles carry theirs nested: `TRACKS\TRACKB12.BUN` alone has
1,135 solids. Across the disc there are 1,465 solids and 22,280 strips.

Reader: `tools/geometry_convert.py` (`--list` for the table, otherwise
Wavefront OBJ + MTL; `--split` for one OBJ per solid; stdlib only).

The struct layouts below are the engine's own, from the recovered `.mdebug`
type information in `docs/mdebug_structs.txt`. The VU1 packet layout was
recovered from the packets themselves and then confirmed against
`eStripDataE::GetElementXYZ` at `0x0011c7b8` in the ELF, which computes the
same addresses.

## Chunk tree

```
0x80034000  solid list
  0x00034001   52 bytes    eSolidListHeader -- the authoring filename
  0x80034002               one container per solid
    0x00034003  192 bytes  eSolid
    0x00034006  8 * n      eTextureTable[]       {NameHash, pTextureInfo}
    0x0003401d  8 * n      eLightMaterialEntry[] {NameHash, pLightMaterial}
    0x00034004  64 * n     eStripEntry[NumStrips]
    0x00034005             the VU1 packet for every strip, back to back
```

Chunks are 16-byte aligned by padding the **front** of the payload with `0x11`
filler bytes (see `docs/formats/bchunk.md`), so `0x00034003` is sometimes 204
bytes rather than 192 and `0x00034004` sometimes `64 * NumStrips + 8`. Skip
the leading `0x11` run before reading any of these.

## `eSolid`, 192 bytes

| offset | type        | field |
|-------:|-------------|-------|
| 0x08   | `u32`       | `NameHash` |
| 0x0C   | `u32`       | `Version` |
| 0x10   | `char[24]`  | `Name` |
| 0x30   | `u16`       | `Flags` |
| 0x32   | `u16`       | `StripFlags` |
| 0x34   | `u16`       | `NumStrips` |
| 0x36   | `u16`       | `NumPolys` |
| 0x38   | `u16`       | `NumVerts` |
| 0x3A   | `u16`       | `NumOriginalVerts` |
| 0x3C   | `u32`       | `SizeofStripEntryData` |
| 0x40   | `float[4]`  | `AABBMin` |
| 0x50   | `float[4]`  | `AABBMax` |
| 0x60   | `float[16]` | `PivotMatrix` |
| 0xA0   | `ptr`       | `AnimationTree` |
| 0xA8   | `ptr`       | `pRigidAnimation` |
| 0xAC   | `u16`       | `NumTextureTableEntries` |
| 0xAE   | `u16`       | `NumLightMaterials` |
| 0xB0   | `ptr`       | `StripEntryTable` |
| 0xB4   | `ptr`       | `StripEntryDataStart` |
| 0xB8   | `ptr`       | `pTextureTable` |
| 0xBC   | `ptr`       | `LightMaterialTable` |

`AABBMin`/`AABBMax` are exact: every decoded vertex of all 1,465 solids falls
inside its own box, which is the cheapest check that a decoder is correct.

`NumPolys` is **not** reliable -- for 19 of the 1,465 solids it disagrees with
the sum of its own strips' `eStripEntry.NumPolys`. The per-strip counts are
the truth; the header field is stale in the shipped data.

`NumTextureTableEntries` at 0xAC is worse than stale: it is **zero on every
one of the 1,411 solids** in `CARS\*\GEOMETRY.BIN` and the two track
bundles, including the solid whose `0x00034006` table has 28 entries. The
field is real -- it is where `eSolid::GetNumTextures()` reads -- but nothing
the exporter ran ever wrote it, so the only way to know how many textures a
solid references is to divide the `0x00034006` chunk's own size by 8. A port
that sizes a texture array from the header field gets zero textures on the
whole disc and no error to go with it.

`NumLightMaterials` at 0xAE, two bytes further on, is the opposite: it agrees
with the size of its `0x0003401d` table on all 1,411. Either source works for
that one.

## `eStripEntry`, 64 bytes, one per strip

| offset | type    | field |
|-------:|---------|-------|
| 0x00   | `u32`   | `TextureNumber` -- indexes this solid's `0x00034006` table |
| 0x04   | `u16`   | `TextureWidthScale` |
| 0x06   | `u16`   | `TextureHeightScale` |
| 0x08   | `ptr`   | `Data` (fixed up at load; meaningless in a file) |
| 0x0C   | `u16`   | `DataQWordSize` |
| 0x0E   | `u16`   | `Flags` |
| 0x10   | `float[3]` | `AABBMin` |
| 0x1C   | `u8`    | `PolyGroupNumber` |
| 0x1D   | `u8`    | `NumVerts` |
| 0x1E   | `u8`    | `NumPolys` |
| 0x1F   | `s8`    | `LightMaterialIndex` (-1 = none) |
| 0x20   | `float[3]` | `AABBMax` |
| 0x2C   | `u32`   | `pad` |
| 0x30   | `u16[4]`| `Nx`, `Ny`, `Nz`, `Nt` |
| 0x38   | `f32`   | `MaterialDensity` |
| 0x3C   | `u16`   | `MipMapK` |
| 0x3E   | `s8`    | `MipMapL` |
| 0x3F   | `s8`    | padding |

`DataQWordSize * 16` is the strip's slice of `0x00034005`; walking the entries
in order walks the packet data in order.

`NumVerts`, `NumPolys` and `LightMaterialIndex` are **an exact copy** of what
the strip's own VU header quad says -- checked on all 18,848 strips of the 28
car files and the two track bundles, zero disagreements. (`LightMaterialIndex`
is the packet's byte divided by four; see the header quad below.) That
redundancy is worth knowing about, because it means a renderer can size every
buffer it needs, and skip every strip it does not want, straight from the
64-byte entry table without replaying a single VIF packet.

`TextureWidthScale`/`TextureHeightScale` are 1.15 fixed point and are 32768
(= 1.0) for every strip on the disc, so `eSolid::FixStripSTs()` is a no-op
here and ST needs no scaling.

`TextureNumber` is how a strip finds its texture, and it is the only link
between geometry and the `0xb0300001` packs. It indexes the solid's own
`0x00034006` table, which is the table whose length the `eSolid` header
refuses to tell you (above). Of the 18,848 strips, 18,823 index inside their
table -- and **25 index exactly one past the end**, `TextureNumber ==
NumTextures`: one strip of `TS50_C`, and four each in the four
`XS_CURVE35*_S*_00` track pieces. That is the untextured sentinel, so a
renderer must test `TextureNumber >= NumTextures` and draw those strips
untextured rather than trusting the index. Nothing larger than that occurs;
the values run 0..27 across the disc.

## The VU1 packet, `0x00034005`

Each strip's slice is raw VIF1 code: a run of UNPACKs, then MSCAL, then NOP
padding. A VIFcode is `CMD(31:24) | NUM(23:16) | IMM(15:0)`; it is an UNPACK
when `cmd & 0x60 == 0x60`, with `vn = (cmd >> 2) & 3` (S/V2/V3/V4) and
`vl = cmd & 3` (32/16/8/5-bit). `IMM` bit 15 is FLG, bit 14 USN, bits 13..0
the destination VU address.

Replay the UNPACKs into a VU memory image of quads and read the vertices back
out by address. The byte order on its own will mislead you -- the addresses
are what identify each field:

| address | unpack | holds |
|--------:|--------|-------|
| 0   | `V4-8`  | `NumVerts`, `NumLoops`, `3 * NumVerts`, `4 * LightMaterialIndex` |
| 1   | `V4-32` | the ADC bits (below) |
| 2   | `V4-32` | XYZ |
| 32  | `V4-32` | ST |
| 52  | `V4-5`  | RGBA5551, one quad per vertex |
| 92  | `V4-8`  | normals, signed (optional) |

`NumVerts` is at most 30 and `NumLoops == (NumVerts - 1) >> 2`. The light
material byte is the `eStripEntry.LightMaterialIndex` times four, so read it
as signed and divide (-4 is "none").

### Transposed fields

XYZ and the normals are stored in groups of four vertices, **transposed**: one
quad of four X, one of four Y, one of four Z, then the next four vertices.
Vertex `v` reads lane `v % 4` of

```
XYZ      2 + 3 * (v // 4) + component
normal  92 + 3 * (v // 4) + component
```

A trailing group of fewer than four vertices keeps the same layout and is
unpacked with a narrower VIFcode -- `S-32`, `V2-32` or `V3-32` (`NUM=3`) for
XYZ, still `V4-8` for the normals. `eStripDataE::GetElementXYZ` walks exactly
this: a 48-byte stride per group of four, `+16` for Y and `+32` for Z, `+4` at
each group boundary to step over the VIFcode.

ST is transposed the same way -- one quad of four S, one of four T, address
`32 + 2 * (v // 4) + component` -- but its trailing group is **interleaved**
instead: S and T pairs packed end to end from quad `32 + 2 * (NumVerts // 4)`.

Colours are never transposed. The `V4-5` unpack expands one RGBA5551 halfword
per vertex into the quad at `52 + v`, with R in bits 0..4, G in 5..9, B in
10..14 and A in bit 15.

Normals are signed bytes: unit vectors quantised onto a sphere of radius 127.
Their integer length therefore lands in **125..127** -- never above, because
127 is the radius, and never far below, because only the rounding of three
components loses any. Measured over every strip of all 28 `CARS\*\GEOMETRY.BIN`,
192,822 of 192,822 non-zero normals are inside that band and the shortest is
125.355. That band is the other cheap check that a decoder is correct; an
earlier draft of this file said "126 or 127", which rejects 16% of the real
data.

53 of those 192,875 normals are **exactly zero**. They are in the shipped
data, so a decoder should not treat a zero normal as a failure -- but it also
must not treat one as "this strip has no normals", because roughly 17% of
strips genuinely have no normal field at all and that is a different
condition. Test whether the `V4-8` unpack at address 92 ever happened, not
whether a vector is zero.

### The ADC bits

The 16 bytes at address 1 are `eStripData::GetADCBits()`'s two words plus
padding. They are a **per-vertex** bitfield: a set bit means that vertex does
not kick a triangle. Vertices 0 and 1 are always set -- a strip needs three
vertices before it can draw anything. Vertex `v`'s bit is

```
v <= 14     bit 14 - v                 of the low word
v >= 16     bit 4 * NumLoops + 5 - v   of word 3
```

and which quad word is the low one depends only on `NumLoops`:

| `NumLoops` | low word |
|-----------:|----------|
| 0, 1, 2    | word 0 |
| 3          | word 3 |
| 4, 5, 6    | word 0 |
| 7          | word 2 |

Vertex 15 has no bit of its own: the low word's field ends at 14 and the high
word's begins at 16. It does not need one, because suppressed vertices always
come in adjacent pairs `{r, r+1}` -- one restart of the strip -- so a lone bit
at 14 or 16 implies 15. Bits outside those fields are unrelated flags (word 3
bit 22, for instance, is set on every `NumLoops == 7` strip) and must not be
read as vertices.

This reproduces `eStripEntry.NumPolys` for all 22,280 strips, and the pairing
holds for all of them:

```
NumPolys == NumVerts - 2 - (number of suppressed vertices in [2, NumVerts))
```

### Winding

A restart also restarts the winding. The sub-strip beginning at `r` draws
`(r, r+1, r+2)` first, so the parity that decides whether a triangle is
`(v-2, v-1, v)` or `(v-2, v, v-1)` is measured from `r`, not from 0. Getting
this wrong is invisible in the polygon count and very visible in a renderer.

Checked against the per-vertex normals, this is right for 99.65% of the game's
triangles. The rest are concave corners where a smoothed vertex normal
genuinely disagrees with its face -- strips with no restart at all agree
100%, which is what pinned the rule down.

Note that the PS2's GS has no hardware backface culling (the VU does it), so
nothing in the data forces a consistent winding; the normals are the only
evidence for it.

## Light materials and textures

`0x0003401d` is `eLightMaterialEntry[NumLightMaterials]` and `0x00034006` is
`eTextureTable[NumTextureTableEntries]`; both are 8 bytes per entry, a
`bStringHash` name hash followed by a pointer fixed up at load time.
`eStripEntry.LightMaterialIndex` indexes the first and `eStripEntry`'s
`TextureNumber` the second. Resolve the hashes with `tools/bhash.py`; the
texture hashes point into the `0xb0300001` packs described in
`docs/formats/texture-pack.md`, where `texpack_find()` takes a name hash
directly and `texpack_upload()` hands back a `C3D_Tex`.

`TRACKS\TRACKA12.BUN` contains **no** `0x80034000` at all -- it is the other
half of the track data. All 1,135 track solids are in `TRACKB12.BUN`. A
reader pointed at A12 should report "no solid list" rather than treat an
empty result as a parse failure.

## Cross-check

`3DS Files/source/geometry.c` implements all of the above and is diffed
against `tools/geometry_convert.py` over the shipped data itself, not against
a script:

```bash
python tools/geometry_check.py
```

```
30 files, 42047 lines, 0 differ      (51/51 mutations caught)
```

The transcript carries a per-strip and per-solid FNV-1a digest -- which
covers every vertex without printing tens of millions of lines -- plus the
invariant counts recomputed on both sides. `--detail NAME` switches one named
solid to a full per-vertex dump on both sides, which is what to reach for
when a digest differs.

Over all 30 files: 1,411 solids, 18,848 strips, 0 vertices outside their
solid's AABB, 0 normals outside the 125..127 band, and the decoded triangle
count equal to `eStripEntry.NumPolys` on every single strip.

`python tools/geometry_mutate.py` is the deck that keeps that honest: 51
single-edit changes to the decoder, each one a behavioural claim made above,
all 51 caught, in about two minutes. Six further changes are listed there as
*equivalent* rather than missed, each with the measurement that proves it
cannot reach the output -- the VIFcode census, the always-set ADC bits 0 and
1, the redundant entry table, and so on. Two of those are equivalent only
because of what this particular disc contains, and say so.

Two defects came out of writing the port, both fixed above:

* this document said normals were "length 126 or 127", which rejects 16% of
  the real data;
* the first `geo_decode_next` did not advance its cursor past a strip it
  could not decode, so the obvious caller loop spun forever on damaged data.
  A mutation that made every packet unreadable found it by printing 72
  million lines in sixty seconds.
