# Texture streaming -- TexturePack's streaming half

A TexturePack made with no file name can hold a table without its pixels.
LoadTextureTableFromFile reads only the start of a texture-pack file: the
`0xb0300001` chunk's header and its table. The pixels are read later, a
few at a time, when something asks for a texture by name. Retail's
LoadGlobalChunks makes three such packs, over `GLOBAL\DYNTEX.BIN`,
`GLOBAL\HUDTEX.BIN` and `CARS\TEXTURES.BIN`. CarLoader streams each car's
skins out of the third, and the track flow streams the HUD's textures out
of the second. The port has the code in `texturestream.{c,h}`, beside
`texturepack.{c,h}` (`docs/formats/texture-pack.md`) and over QueuedFile
(`docs/formats/resource-file.md`).

Retail's ELF is stripped. The addresses below are retail's with the
demo's beside them, and the names are the demo's. Apart from the field
offsets, the code is the same in both, and the port follows retail.

| | retail | demo |
|---|---:|---:|
| `TexturePack::LoadTextureTableFromFile(const char *)` | 0x001ac608 | 0x001a1f00 |
| `TexturePack::FindLoadedTextureData(int, int)` | 0x001ac780 | 0x001a2078 |
| `TexturePack::FindNotYetLoadedNeighbourTextureData(int, int, int)` | 0x001ac7d0 | 0x001a20c8 |
| the list's sort compare (no symbol) | 0x001ac850 | |
| `TexturePack::AddLoadedTextureData(int, int)` | 0x001ac880 | 0x001a2148 |
| `TexturePack::RemoveLoadedTextureData(int, int)` | 0x001aca30 | 0x001a22e8 |
| `TexturePack::DeleteLoadedTextureData(LoadedTextureData *)` | 0x001aca88 | 0x001a2340 |
| `TexturePack::LoadTextureFromFile(TextureInfo *)` | 0x001acaf8 | 0x001a23b0 |
| `TexturePack::UnloadTextureFromFile(TextureInfo *)` | 0x001acb68 | 0x001a2420 |
| `TexturePack::LoadTexturesFromFile(unsigned int *, int, void (*)(int), int)` | 0x001acc98 | 0x001a2550 |
| `TexturePack::UnloadTexturesFromFile(unsigned int *, int)` | 0x001acd90 | 0x001a2648 |
| `TexturePack::ServiceLoadingTextures()` | 0x001ace00 | 0x001a26b8 |
| `TexturePack::ReadCallback(int)` | 0x001acf28 | 0x001a27e0 |
| `TexturePack::UnloadAllTexturesFromFile()` | 0x001acf98 | 0x001a2850 |
| `TexturePack::GetLoadedSize()` | 0x001ad008 | 0x001a28c0 |
| `TexturePack::ReadCallbackBridge(int, int)` | 0x001ad608 | 0x001a2eb0 |
| `LoadedTextureData::~LoadedTextureData()` | 0x001ad610 | 0x001a2eb8 |
| `LoadGlobalChunks()` | 0x001682d0 | |
| `pDynamicTexturePack` | gp-21432 | |
| `pHudTexturePack` | gp-21428 | |
| `pCarTexturePack` | gp-21436 | |

Not ported:

- PrintNameHashes (`0x001acbd8`) and PrintLoadedTextureData
  (`0x001acc30`). Their prints are compiled out, and nothing calls them.
- StreamingTexturePack (`0x001ad048` to `0x001ad450`). Nothing calls its
  Init.

## The records

```
LoadedTextureData, 44 bytes            TexturePack's streaming fields
  0  bNode (next, prev)                 40  char Filename[64]
  8  s32  LowPos                       124  s32  TextureDataFilePos
 12  s32  HighPos                      128  bList LoadedTextureDataList
 16  s32  NumAssignments               136  LoadedTextureData *CurrentLoadingTextureData
 20  s32  MemoryPool                   140  s32  NumNotYetLoadedTextureDatas
 24  u8  *Buf                          144  s32  MemoryPool (the constructor sets 64)
 28  s32  LoadingCompleted
 32  s32  LoadingInProgress
 36  void (*Callback)(int)
 40  s32  CallbackParam
```

A LoadedTextureData is a range `[LowPos, HighPos)` of the blob's payload,
with a count of its users. `Buf` is its block once the range is being
read. `LoadingCompleted` means the read is in. A range with no `Buf` and
`LowPos == HighPos` is empty: LoadTexturesFromFile's callback rides the
list in one. Each record is `bMalloc(44, "LoadedTextureData", 0, 16)`.
A range's block is `bMalloc(HighPos - LowPos, "LoadedTextureData", 0,
MemoryPool)`, from the pack's pool word.

## LoadTextureTableFromFile

1. The file name goes into `Filename`, at most 63 characters and a NUL.
   Every read of the pack's pixels goes there. Nothing else happens if
   the file does not open.
2. It reads the file's first 128 KB, or less if the file is shorter, into
   a block from `bMalloc(n, "TextureTable", 0, 72)`, and closes it.
3. The pack chunk's first leaf is the 84-byte header. The table leaf
   follows it, at `16 + header size`, and the blob's leaf follows that, at
   `table + 8 + table size`. The table is used only when the read reaches
   the blob's leaf: that leaf's offset is at most the bytes read.
   - The table, `table size / 164` records, is copied into a block of its
     own, `bMalloc(n * 164, Name, 0, 16)`, and attached
     (AttachTextureTable), and `pTextureInfoNeedsToBeFreed` is set.
   - `TextureDataFilePos` is where the blob's payload starts in the file,
     rounded up to 128, as LoaderTexturePack rounds a loaded pack's
     (`docs/formats/texture-pack.md`).
4. The 128 KB block is freed whether or not the table was used.

A file whose header and table end past 128 KB keeps no table, so none of
its textures can be found. The disc's three files are well inside it.

## Ranges: Find, Add, Remove and Delete

**FindLoadedTextureData(pos, size)** answers the first range on the list
that holds `[pos, pos + size)`, read or not.

**FindNotYetLoadedNeighbourTextureData(pos, size)** answers the first range
with no `Buf` that the new one ends within 1 KB before, or starts within
1 KB after:

- `LowPos - 1024 <= pos + size <= LowPos`, or
- `HighPos <= pos <= HighPos + 1024`.

Its third argument is never read.

**AddLoadedTextureData(pos, size)**:

1. A range that holds it gains one user.
2. Otherwise a neighbour not yet read grows to take it in and gains one
   user. Then, if the grown range is now a neighbour of a second one, the
   two merge: the bounds widen, the users add up, and the second is
   unlinked and freed. `NumNotYetLoadedTextureDatas` drops by one. Neither
   case sorts the list again.
3. Otherwise a new range goes on the list's tail, with one user, the
   pack's `MemoryPool` and no `Buf` or callback.
   `NumNotYetLoadedTextureDatas` gains one, and the list is sorted
   (bList::Sort).

The compare says two ranges are in order when either has a callback, and
otherwise when the first's `LowPos` is not above the second's.

**RemoveLoadedTextureData(pos, size)** answers 0 when no range holds it.
Otherwise the range loses a user, and if that was its last and it is not
being read, it is deleted. Then it answers 1.

**DeleteLoadedTextureData(d)** clears the pack's records that point into
the range (UnAssignTextureData), if its read is in. If it is not,
`NumNotYetLoadedTextureDatas` drops by one. Then, after
eWaitUntilRenderingDone, the range is unlinked and freed with its block.

**LoadTextureFromFile(t)** adds the record's pixels as a range, and its
palette as another. A size of 0 is skipped. **UnloadTextureFromFile(t)**
removes them the same way. Neither one services.

## LoadTexturesFromFile and UnloadTexturesFromFile

LoadTexturesFromFile loads each of the `n` hashes it is given. A hash of 0
is passed over, and so is a hash the pack does not have (GetTexture).
With a callback, an empty range goes on the list's tail, unsorted, with
the callback and its parameter. It has no users, and
`NumNotYetLoadedTextureDatas` gains one. Then the pack is serviced.

UnloadTexturesFromFile unloads each of its hashes, with the same two
skips, and does not service.

## ServiceLoadingTextures and ReadCallback

**ServiceLoadingTextures** does nothing while a range is being read or
while `NumNotYetLoadedTextureDatas` is 0. Otherwise it takes the first
range on the list with no `Buf`:

- **An empty one** is unlinked. Its callback, if any, is called with its
  parameter, the range is freed, and the service runs again.
- **A real one** is marked as being read, becomes
  `CurrentLoadingTextureData`, and `NumNotYetLoadedTextureDatas` drops by
  one. It gets its block, and its read is queued:
  `AddQueuedFile(Buf, Filename, TextureDataFilePos + LowPos, HighPos -
  LowPos, ReadCallbackBridge, pack)`.

So one range is read at a time, and the list's order is the read order.

**ReadCallback(error)**, through the bridge, takes the range just read. It
clears `CurrentLoadingTextureData` and assigns the block over the range
(AssignTextureData), so every record whose pixels or palette lie in it
points there. It marks the range read and not being read, and runs
eFixUpTables. If the range lost its last user while it was read, it is
deleted. Then the pack is serviced again. A failed read is assigned the
same way: `error` is never looked at.

**UnloadAllTexturesFromFile** sets every range's users to 0 and deletes
every range not being read. Then it sets `NumNotYetLoadedTextureDatas`
to 0. **GetLoadedSize** adds up every range's length, read or not.

`~TexturePack` waits out a read in flight: while
`CurrentLoadingTextureData` is set, it runs ServiceQueuedFiles. Then it
frees each range. `~LoadedTextureData` frees the block, and with bit 0
of its flags, the record.

## Retail's oddities, kept

- **An empty range counts up.** Where an empty range is taken off, the
  service sets `NumNotYetLoadedTextureDatas` to its value at the start
  plus one, not minus one. The count only gates the service, and every
  range not yet read is still on the list. So a count above the truth
  costs a walk of the list and nothing more. UnloadAllTexturesFromFile
  puts it back to 0.
- **A callback can be lost.**
  - The neighbour search does not skip an empty range. A range that
    starts at most 1 KB into the blob, asked for while a callback waits,
    grows the empty range into a real one. The callback is then never
    called, because only an empty range's callback is.
  - A range merged in as the second neighbour is freed with its
    callback.
- **A callback is a barrier.** The compare puts a callback's range in
  order with anything, so the sort never moves a range across it. A
  range asked for after a callback is read after it, even when it lies
  before the ranges the callback waits for. The callback still fires
  once exactly the ranges asked for before it are in.
- **A range emptied with no callback** is taken off as a callback's is,
  and nothing is called.

## LoadGlobalChunks' packs

With `TheDemoDiscManager.bActive` 0, LoadGlobalChunks (`0x001682d0`)
does the following:

1. It loads GLOBALA and GLOBALB, and waits.
2. It makes `pDynamicTexturePack`:
   `bMalloc(148, "pDynamicTexturePack", 0, 16)`, TexturePack
   `("DynTextures", NULL)`, and LoadTextureTableFromFile
   (`"GLOBAL\DYNTEX.BIN"`).
3. It sets English.
4. It asks for `LOADING` (`0xab0e817d`), unless GetLoadedTexture already
   has it.
5. It services the resource system until nothing is loading and
   DynTextures is reading nothing.
6. It shows LOADING_TRACK and its copyright line, and draws one frame.
7. It makes `pHudTexturePack` (`"HudTexturePack"`, `"HudTextures"`,
   `"GLOBAL\HUDTEX.BIN"`) and `pCarTexturePack` (`"pCarTexturePack"`,
   `"CarTextures"`, `"CARS\TEXTURES.BIN"`) the same way.
8. It waits as in step 5.

The demo disc's branch asks DynTextures for `FIRSTLEGAL`, `DISCLAIMER`
and two more, and shows its own screen. The port leaves it out.

## The port

- **The records.** A disc record is 164 bytes, and the host's TextureInfo
  is larger, because its pointers are 8 bytes. The table is converted
  record by record: the 128 bytes after the node are copied as they are,
  and the pointer fields are left for AttachTextureTable to set. The
  host's LoadedTextureData is `sizeof` it, not 44.
- **Positions** are added and subtracted as 32-bit words that wrap, as
  the image's are.
- **The reads** go through `queuedfile.c` and `bfile.c`. A read lands at
  once, and its callback runs on the next bServiceFileSystem, so a range
  is in the frame after it is queued.
- **`main.c`** makes the three packs:
  - DynTextures, its LOADING and the wait come before
    `bgf_load_global_chunks`, which sets English and draws the frame.
    Retail sets English between the table and the ask. On a fresh boot
    that renames nothing, so the order makes no difference.
  - HudTextures, CarTextures and the second wait come after it.
  - Then CarLoader's two seams and the track flow's
    UnloadAllTexturesFromFile point here.

  MainLoop's ServiceResourceLoading runs the queued reads every frame.
  The frame LOADING shows is still drawn from the UI's DYNTEX bundle, not
  from this pack.
- **The one check the image hasn't.** Before step 3, the port checks that
  the table's leaf and its size word lie inside the bytes read. If they
  don't, the file isn't a pack: it keeps no table, as a file that doesn't
  open keeps none, and stderr says so. The image takes the header's word
  for it. On 2026-10-21 a friend's New 3DS faulted reading 1.7 GB past the
  buffer, because `GLOBAL\HUDTEX.BIN` on their card held another file.
  `zdir_extract.py` had named another release's directory by index. Where
  the check holds, the image's own test decides as before, so the checker
  doesn't see it.
- **A pack with no table stops the port.** Every streamed pack on the disc
  has one, so `newStreamedPack` takes a pack without one to mean a card
  that lacks the disc's file. It puts the file's path on screen with the
  README's fix and exits when START is pressed. It doesn't run on with the
  HUD or the cars untextured.
- eWaitUntilRenderingDone is still NULL on the device, as it is for the
  resource system.

## Checked by

`tools/texturestream_check.py` runs everything above as shipped, in
RetailEmu. That includes TexturePack's constructor and destructor,
AttachTextureTable, Assign and UnAssignTextureData, GetTexture, all of
QueuedFile, bList::Sort and the string calls. Both sides stub the file
calls (over a fake file system), bMalloc and bFree (over a fake heap), the
slot pool, eWaitUntilRenderingDone, eFixUpTables, Joylog and the
callbacks. The checker diffs the result against the port in
`tools/src/texturestream_test.c`. After each op the transcript holds every
pack, its ranges and loaded textures, the queued reads and every back
link.

The files are the disc's own `GLOBAL\DYNTEX.BIN`, `GLOBAL\HUDTEX.BIN` and
`CARS\TEXTURES.BIN`, loaded and streamed as LoadGlobalChunks and
CarLoader load them. Then there are packs the checker builds:

- tables at the 128 KB edge and past it;
- a file that stops before its blob;
- a table of a size no record divides;
- names with no NUL;
- garbage in every field the table's copy keeps;
- placements laid out for the 1 KB edges, merges of two, contained
  ranges and a callback's empty range found as a neighbour;
- a hash-0 record.

The scenarios:

- `s_tables`: the table edges, and a missing file;
- `s_hud`, `s_car` and `s_global`: LoadGlobalChunks' and CarLoader's
  loads over the disc's files;
- `s_ranges`: the 1 KB edges and the merges;
- `s_records`: Load and UnloadTextureFromFile, a range that keeps the
  pool word it was made with after the pack's changes, and a palette
  larger than its image;
- `s_markers`: the lost callbacks, including one lost to a range that
  only reaches it once grown; the barrier, including a range that starts
  below a callback's 0; two ranges that start together; a callback that
  loads again from inside itself; and the count poked so the service
  stalls;
- `s_remove`: a user let go while its range is read, and the emptied
  range;
- `s_failed`: a file that does not open, and a read past its end.

9 scenarios, 380 ops and 7353 lines give 0 differ.

```bash
python tools/texturestream_check.py
python tools/texturestream_check.py --mutate [--only a,b]
```

Of its 142 mutations, the first full pass caught 136. Two of the six it
missed were not mutations of anything the scenarios reached. One poked a
range at 6000, inside a range already loaded, and moved to 7000. The other
was a marker's callback run after its free, which a marker, having no
block, cannot tell; it now frees before the call. The other four got cases
of their own: a palette larger than its image (`R7.BIN`), a range below a
callback's 0, two ranges that start together, and a range grown into a
callback's. A second full pass caught all 142, with none equivalent. A
mutant that hangs, as one that breaks the sort's order does, is killed
after 60 s and counts as caught.
