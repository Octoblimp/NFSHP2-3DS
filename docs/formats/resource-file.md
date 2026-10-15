# ResourceFile and QueuedFile

Retail's ResourceFile.cpp loads whole files and hands them to LoadChunks:
the bundles, the tracks and the cars. QueuedFile.cpp is the queue of file
reads underneath it, which the streaming texture packs share. The port
has them in `resource.{c,h}` and `queuedfile.{c,h}`, over a port-only
`bfile.{c,h}`. Retail's ELF is stripped, so the addresses below are
retail's with the demo's beside them, and the names are the demo's. The
code is the same in both.

| | retail | demo |
|---|---:|---:|
| `ResourceFile::ResourceFile(const char *, ResourceFileType, int, void (*)(int), int)` | 0x00199320 | 0x0018f918 |
| `ResourceFile::AllocateMemory(int)` | 0x00199408 | 0x0018fa00 |
| `ResourceFile::~ResourceFile()` | 0x00199458 | 0x0018fa50 |
| `ResourceFile::LoadResourceIfFileTransferFinished()` | 0x001994f0 | 0x0018fae8 |
| `ResourceFile::FileTransferCallback(int, int)` | 0x001995d0 | 0x0018fbc8 |
| `ResourceFile::GetSize(int, int *)` | 0x001995e0 | 0x0018fbd8 |
| `LoadResourceFile(const char *, ResourceFileType, int, void (*)(int), int)` | 0x00199640 | 0x0018fc38 |
| `LoadResourceFile(const char *, ResourceFileType, int, int, void (*)(int), int)` | 0x001996f0 | 0x0018fce8 |
| `ChangeFilenameForHotChunking(ResourceFile *, const char *)` | 0x00199720 | 0x0018fd18 |
| `UnloadResourceFile(ResourceFile *)` | 0x00199728 | 0x0018fd20 |
| `ServiceResourceLoading()` | 0x00199788 | 0x0018fd80 |
| `IsResourceLoadingComplete()` | 0x00199818 | 0x0018fe10 |
| `FindResourceFile(const char *)` | 0x00199828 | 0x0018fe20 |
| `FindResourceFile(ResourceFileType)` | 0x00199890 | 0x0018fe88 |
| `GetResourceFileSize(ResourceFileType, int, int *)` | 0x001998c8 | 0x0018fec0 |
| `_GLOBAL_$D$LoaderNull__FP6bChunk` | 0x00199a38 | 0x00190030 |
| `_GLOBAL_$I$LoaderNull__FP6bChunk` | 0x00199a48 | 0x00190040, `__CTOR_LIST__` [39] |
| `ResourceFile::ChangeFilenameForHotChunking(const char *)` | 0x00199a60 | 0x00190058 |
| `QueuedFile::QueuedFile(void *, const char *, int, int, void (*)(int, int), int)` | 0x001ad6d8 | 0x001a2f80 |
| `QueuedFile::BeginRead()` | 0x001ad760 | 0x001a3008 |
| `ServiceQueuedFiles()` | 0x001ad850 | 0x001a30f8 |
| `FindQueuedFile(int)` | 0x001ad9d8 | 0x001a3280 |
| `InitQueuedFiles()` | 0x001ada10 | 0x001a32b8 |
| `CloseQueuedFiles()` | 0x001ada40 | 0x001a32e8 |
| `AddQueuedFile(void *, const char *, int, int, void (*)(int, int), int)` | 0x001ada60 | 0x001a3308 |
| `ChangeQueuedFileParams(int, int, int)` | 0x001adb08 | 0x001a33b0 |
| `AbortQueuedFile(int)` | 0x001adb48 | 0x001a33f0 |
| `_GLOBAL_$D$QueuedFileSlotPool` | 0x001adc68 | 0x001a3510 |
| `_GLOBAL_$I$QueuedFileSlotPool` | 0x001adc78 | 0x001a3520, `__CTOR_LIST__` [52] |
| `QueuedFile::ReadDoneCallback(bFile *, int)` | 0x001adc90 | 0x001a3538 |
| `QueuedFile::SortByPriority(QueuedFile *, QueuedFile *)` | 0x001adca0 | 0x001a3548 |
| `HotChunkFilesNeedUpdating` | gp-19960 | 0x00323b80 |
| `ResourceFileList` | gp-19952 | 0x00323b88 |
| `NumResourcesBeingLoaded` | gp-19944 | 0x00323b90 |
| `QueuedFileSlotPool` | gp-19120 | 0x00323eb0 |
| `QueuedFile::CurrentHandle` | gp-19116 | 0x00323eb4 |
| `QueuedFileReadInProgress` | gp-19112 | 0x00323eb8 |
| `QueuedFileList` | gp-19104 | 0x00323ec0 |

## The records

```
ResourceFile, 216 bytes               QueuedFile, 100 bytes
  0  bNode (next, prev)                 0  bNode (next, prev)
  8  ResourceFileType Type              8  void *pBuf
 12  s32  Flags                        12  char Filename[48]
 16  char Filename[80]                 60  s32  FilePos
 96  char HotFilename[80]              64  s32  NumBytes
176  s32  FileTransfersInProgress      68  s32  NumRead
180  s32  LoadingFinishedFlag          72  s32  BlockSize
184  void (*Callback)(int)             76  s32  Priority
188  s32  CallbackParam                80  void (*Callback)(int, int)
192  bChunk *pFirstChunk               84  s32  CallbackParam
196  s32  SizeofChunks                 88  s32  Handle
200  void *pLoadedHotFileEntries       92  QueuedFileStatus Status
204  s32  NumLoadedHotFileEntries      96  s32  AbortFlag
208  s32  HotFileNumber
212  s32  InventoryHandle
```

- ResourceFileType: GLOBAL 0, FRONTEND 1, INGAME 2, TRACK 3, NIS 4,
  CAR 5, LANGUAGE 6, REPLAY 7.
- Flags: HOTCHUNKABLE 1, USE_TEMPORARY_MEMORY 2, FREE_AFTER_LOADING 4,
  LZCOMPRESSED 8.
- QueuedFileStatus: WAITING 0, READING 1, DONE 2, ERROR 3.

A ResourceFile is `bMalloc(216, "ResourceFile", 0, 16)` and goes back
through `__builtin_delete`. A QueuedFile comes from QueuedFileSlotPool,
which InitQueuedFiles makes with `bNewSlotPool(100, 16,
"QueuedFileSlotPool", 16)`. InitializeEverything calls InitQueuedFiles
after LoadConfig and before eMathInit. Nothing calls CloseQueuedFiles.

## ResourceFile

```
ResourceFile(name, type, flags, cb, param)
    Type, Flags = type, flags; bStrCpy(Filename, name)
    Callback, CallbackParam = cb, param
    transfers = finished = HotFileNumber = 0
    hot entries = NULL, 0; InventoryHandle = 0; HotFilename[0] = 0
    SizeofChunks = max(bFileSize(Filename), 0)    // -1 when missing
    pFirstChunk = NULL
    if SizeofChunks:
        AllocateMemory(Flags & LZCOMPRESSED)
        transfers++
        h = AddQueuedFile(pFirstChunk, Filename, 0, SizeofChunks,
                          FileTransferCallback, this)
        ChangeQueuedFileParams(h, 5, 0x02000000)

AllocateMemory(top)
    pool = (Flags & USE_TEMPORARY_MEMORY) ? 72 : 64
    if top: pool |= 8
    pFirstChunk = bMalloc(SizeofChunks, Filename, 0, pool)

FileTransferCallback(this, error)     transfers--, whatever the error

LoadResourceIfFileTransferFinished()
    if finished || transfers: return
    if Flags & LZCOMPRESSED and pFirstChunk and it starts "COMP":
        packed = pFirstChunk; pFirstChunk = NULL
        SizeofChunks = packed's word at +8         // the expanded size
        if SizeofChunks:
            AllocateMemory(0)
            LZDecompress(packed, pFirstChunk)
        bFree(packed)
    LoadChunks(pFirstChunk, SizeofChunks)
    if Flags & FREE_AFTER_LOADING:
        if pFirstChunk: bFree(pFirstChunk)
        pFirstChunk = NULL; SizeofChunks = 0
    PostLoadFixup()
    finished = 1

~ResourceFile()
    eWaitUntilRenderingDone()
    if hot entries: bFree them; NULL, 0; HotChunkFilesNeedUpdating++
    if InventoryHandle: bRemoveCodeineInventory(InventoryHandle)
    if pFirstChunk:
        UnloadChunks(pFirstChunk, SizeofChunks)
        bFree(pFirstChunk); pFirstChunk = NULL
        PostLoadFixup()
```

- Pool word 0x40 is a 128-byte boundary in `bMalloc(int, int)`. LoadChunks
  needs that, because a bundle's chunks are aligned to their file offsets.
  Bit 8 takes the block from the top of the bank. A compressed file is read
  into the top and expanded into the bottom, so freeing the packed copy
  leaves no hole.
- A file that is not on the disc, or is empty, gets no buffer and no read.
  It loads as nothing on the next ServiceResourceLoading:
  `LoadChunks(NULL, 0)`, then PostLoadFixup and the callback.
- A read that fails still counts as done. FileTransferCallback ignores the
  error, so the file loads whatever the buffer held, which is the heap's
  leftovers. The LZ step looks for the `COMP` magic, so a failed compressed
  read is handed to LoadChunks unexpanded.
- With FREE_AFTER_LOADING, the buffer is gone once LoadChunks returns. The
  loaders must have copied out anything they keep.

```
LoadResourceFile(name, type, flags, cb, param)
    NumResourcesBeingLoaded++
    rf = new ResourceFile(...); ResourceFileList.AddTail(rf); return rf

LoadResourceFile(name, type, hot, keep, cb, param)        // no callers
    flags = hot != 0; if !keep: flags |= 6
    return LoadResourceFile(name, type, flags, cb, param)

ServiceResourceLoading()
    ServiceQueuedFiles()
    if !NumResourcesBeingLoaded: return 0
    for rf in ResourceFileList, oldest first:
        if rf->finished: continue
        rf->LoadResourceIfFileTransferFinished()
        if !rf->finished: return NumResourcesBeingLoaded
        NumResourcesBeingLoaded--
        if rf->Callback: rf->Callback(rf->CallbackParam)
        return NumResourcesBeingLoaded
    return 0

UnloadResourceFile(rf)
    while !rf->finished: ServiceResourceLoading()
    ResourceFileList.Remove(rf); delete rf

IsResourceLoadingComplete()    NumResourcesBeingLoaded == 0
```

- Each call loads at most one file, in the order they were asked for. A
  file whose read is in waits behind any older file that is still reading.
  The count drops before the callback runs. The return value is read after
  the callback, so it includes any loads the callback asked for.
- Unloading a file that is still loading services the queue until it is
  loaded, which also loads every older file first. Its callback runs
  before it is deleted.
- Both FindResourceFile search from the newest file back: the last match
  by `bStrCmp` on Filename, or by Type. `GetSize(id, &count)` walks the
  file's top-level chunks and adds up the sizes of those with that id, or
  of every chunk when the id is 0. A file with no buffer is 0.
  GetResourceFileSize adds that up over every file of a type.
- ChangeFilenameForHotChunking is `bStrNCpy(Filename, name, 79)`. That
  copies up to 79 bytes, stops after the terminator, and writes no
  terminator when the name runs out first. The read already queued keeps
  the old name.
- The static destructor deletes every file left on the list, loaded or
  not, and leaves the count alone.

## QueuedFile

```
AddQueuedFile(buf, name, pos, n, cb, param)
    qf = new QueuedFile: pBuf, FilePos, NumBytes = buf, pos, n
         NumRead = 0; BlockSize = 0x00100000; Priority = 5
         bStrCpy(Filename, name); AbortFlag = 0; Status = WAITING
         Handle = CurrentHandle; CurrentHandle = (+1 > 100000) ? 1 : +1
    QueuedFileList.AddTail(qf); return qf->Handle

BeginRead()
    f = bOpen(Filename); if !f: Status = ERROR; return
    k = min(NumBytes - NumRead, BlockSize)
    if bFileSize(f) < FilePos + NumRead + k: Status = ERROR
    else:
        Status = READING
        bSeek(f, FilePos + NumRead, 0)
        bReadAsync(f, pBuf + NumRead, k, ReadDoneCallback, this)
        NumRead += k
    bClose(f)

ServiceQueuedFiles()
    bServiceFileSystem()
    if QueuedFileReadInProgress:
        qf = first on the list; status = qf->Status
        if Joylog replaying:
            status = Joylog::GetData(4, 5)
            if status != READING: while qf->Status == READING:
                bServiceFileSystem()
        else: Joylog::AddData(status, 4, 5)
        if status == DONE:
            in progress = 0; qf->Status = WAITING
            if qf->AbortFlag: unlink, delete
            elif NumRead == NumBytes: unlink, cb(param, 0), delete
        elif status == ERROR:
            unlink; in progress = 0; cb(param, 1); delete
        if in progress: return
    if the list is not empty:
        sort it by SortByPriority; first->BeginRead(); in progress = 1
```

- A read moves one block at a time. Between blocks the file goes back to
  WAITING and the list is sorted again, so a lower Priority number queued
  in the meantime goes first. SortByPriority is `!(b->Priority <
  a->Priority)`, and bList::Sort keeps equal priorities in the order they
  were queued.
- AbortQueuedFile removes a WAITING file at once and returns 1. It also
  returns 1 for a handle that is not queued. Otherwise it sets AbortFlag
  and returns 0. The flag is only looked at when a block is done, and the
  file is then dropped with no callback. A file that failed to open still
  reaches the ERROR arm, so its callback still runs, with 1.
- A missing file, or one too short for the next block, fails at BeginRead.
  Its callback runs with 1 at the next service. A read of 0 bytes still
  goes through bReadAsync and completes normally.
- The callback is called after the file is unlinked and before its slot is
  freed. If the callback queues another read, that read gets a new slot.
- Joylog: while replaying, the status is taken from the recording. When
  the recording says the read is over and it is not, the read is waited
  for. On a retail console neither branch runs (joylog.h).

## The port

- `bfile.c` is port-only. It reads over stdio from the extracted tree on
  the SD card, with backslashes turned into slashes. A read lands at once,
  and its callback waits for the next bServiceFileSystem. That way no
  callback runs before bReadAsync returns, as on the console, and bClose
  straight after bReadAsync is safe. A missing file gives a NULL bOpen
  and -1 from `bFileSizeName`. The card holds the tracks' big
  `TRACKB<n>.LZC` expanded, as `TRACKB<n>.BUN`: a .LZC that is not on
  the card is read from its .BUN, which has no `COMP` header and so
  loads as it is. `bFileIsExpanded` says so for a name.
- The decompressor is lzc.c's, which checks its bounds; LZDecompress does
  not. For a whole block, as on the disc, they write the same bytes.
- `bMalloc` keeps the pool word's alignment (`bmem.c`, via memalign),
  and its top, bit 8, as a heap of its own (Session 109). With one
  malloc heap and no top, a packed copy freed after its expansion left
  a hole of megabytes under the expanded block, and so did every file
  read with USE_TEMPORARY_MEMORY (pool 72) and freed once loaded; the
  blocks made while those lived, and kept after, sat between the holes.
  On the 3DS the top is the linear heap (`main.c`'s bMallocTop), which a
  load leaves near empty until the track's meshes and textures go in,
  after the temporaries are freed. It never takes the last 8 MB of it;
  a block that would comes from malloc. bFree knows a top block by its
  address.
- The constructor asks for the top for a compressed file only when the
  card holds it packed (`bFileIsExpanded`). Read from its .BUN, the
  block is the bundle itself, kept for the race: on the top it held
  8.8 MB of the linear heap through the race (TRACKB11), and the
  race's prepare left out 52 to 61 of the track's textures; with the
  bundle in the main heap it leaves out 5 to 7.
  `resource_check`'s file system holds each file as named, so it checks
  the packed case alone.
- A name of 80 characters or more is cut at 79. The image's bStrCpy would
  run it into HotFilename, and a QueuedFile's name past 47 into FilePos.
  The disc's names are far shorter.
- bRemoveCodeineInventory only told the debugger's channel, and
  InventoryHandle is never set, so the call is left out.
- `main.c` runs InitQueuedFiles where InitializeEverything does. It points
  the car loader's three seams, trackflow's FindResourceFile(type),
  racecoord's FindResourceFile(name) and the texture packs'
  ServiceQueuedFiles at these. It runs ServiceResourceLoading after each
  frontend frame, as MainLoop does. The frontend's own bundles still go
  through main.c's synchronous loads. The track viewer borrows the two
  track seams while it unloads, then puts these back.

## Checked by

`tools/resource_check.py` runs everything above as shipped, in RetailEmu,
including LZDecompress, bList::Sort and the string calls. It stubs the
file system, the heap, the slot pool, LoadChunks, UnloadChunks,
PostLoadFixup, the renderer wait, Joylog and four callbacks. It diffs the
result against the port in `tools/src/resource_test.c`. The files are the
disc's own `GLOBAL\PRERACEANIM.LZC` and `CARS\PARCELVAN\GEOMETRY.LZC`, plus
small bundles built by the checker. After each op it prints the globals,
both lists and every back link.

Ten scenarios, 429 ops and 3250 lines give 0 differ. `--mutate` breaks the
port in 155 ways. 153 are caught. The other two cannot be seen:

- `lif_guard_done`: only ServiceResourceLoading calls the function, and
  only for a file that is not loaded yet;
- `dtor_hnum`: the destructor frees the record straight after, and nothing
  reads a freed ResourceFile.
