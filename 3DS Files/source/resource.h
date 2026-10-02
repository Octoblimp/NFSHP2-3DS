// resource -- retail's ResourceFile (0x00199320 .. 0x00199a6c): the files
// the game loads whole and hands to LoadChunks, the bundles and the cars.
// The code is the demo's (0x0018f918 .. 0x00190064), unchanged. Its other
// half, LoadChunks and the loader tables, is bchunkload.c.
//
// LoadResourceFile makes a ResourceFile and puts it at the end of the
// list. Its constructor sizes the file, allocates the buffer and queues
// one read of the whole file (queuedfile.h), at priority 5 and in a single
// block. Each ServiceResourceLoading services the queue, then takes the
// first file on the list that is not loaded yet: once its read is in,
// LoadResourceIfFileTransferFinished expands an LZ-compressed file
// (a `COMP` header) into a buffer of its own, runs LoadChunks over it,
// frees it if it was only wanted while loading, and runs PostLoadFixup.
// Then the count of files loading goes down by one and the file's callback
// runs. That is one file per call, in the order they were asked for. A
// file that is not on the disc loads as nothing, at once.
//
// UnloadResourceFile services the queue until the file is loaded, then
// unlinks and deletes it: the destructor waits for the renderer, runs
// UnloadChunks and PostLoadFixup, and frees the buffer.
//
// The two FindResourceFile search from the newest file back.
//
// Port notes:
//   * The decompressor is lzc.c's, which checks its bounds; the image's
//     LZDecompress (0x001b41c8) does not. For a whole block, as on the
//     disc, they write the same bytes.
//   * A name of 80 characters or more is cut at 79; the image's bStrCpy
//     runs it into HotFilename.
//   * InventoryHandle is never set, and the destructor's
//     bRemoveCodeineInventory only told the debugger's channel, so it is
//     left out. pLoadedHotFileEntries is only set by hot chunking, which
//     is a debug-station feature, but the destructor's half of it is kept.
//
// Cross-checked with queuedfile.c by tools/resource_check.py against the
// retail image; written up in docs/formats/resource-file.md.

#ifndef RESOURCE_H
#define RESOURCE_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"

// ResourceFileType.
enum {
    RESOURCE_FILE_GLOBAL   = 0,
    RESOURCE_FILE_FRONTEND = 1,
    RESOURCE_FILE_INGAME   = 2,
    RESOURCE_FILE_TRACK    = 3,
    RESOURCE_FILE_NIS      = 4,
    RESOURCE_FILE_CAR      = 5,
    RESOURCE_FILE_LANGUAGE = 6,
    RESOURCE_FILE_REPLAY   = 7,
};

// ResourceFileFlags.
enum {
    RESOURCE_FILE_FLAG_HOTCHUNKABLE         = 1,
    RESOURCE_FILE_FLAG_USE_TEMPORARY_MEMORY = 2,
    RESOURCE_FILE_FLAG_FREE_AFTER_LOADING   = 4,
    RESOURCE_FILE_FLAG_LZCOMPRESSED         = 8,
};

// A file's callback, with its parameter, once the file is loaded.
typedef void (*ResourceFileCallback)(intptr_t param);

// ResourceFile, 216 bytes.
typedef struct ResourceFile {
    bNode    Node;                       //   0
    int32_t  Type;                       //   8
    int32_t  Flags;                      //  12
    char     Filename[80];               //  16
    char     HotFilename[80];            //  96
    int32_t  FileTransfersInProgress;    // 176
    int32_t  LoadingFinishedFlag;        // 180
    ResourceFileCallback Callback;       // 184
    intptr_t CallbackParam;              // 188
    uint8_t *pFirstChunk;                // 192
    int32_t  SizeofChunks;               // 196
    void    *pLoadedHotFileEntries;      // 200
    int32_t  NumLoadedHotFileEntries;    // 204
    int32_t  HotFileNumber;              // 208
    int32_t  InventoryHandle;            // 212
} ResourceFile;                          // 216

#if UINTPTR_MAX == 0xffffffffu
typedef char resource_layout_check[
    (sizeof(ResourceFile) == 216 && offsetof(ResourceFile, Filename) == 16
     && offsetof(ResourceFile, HotFilename) == 96
     && offsetof(ResourceFile, FileTransfersInProgress) == 176
     && offsetof(ResourceFile, pFirstChunk) == 192
     && offsetof(ResourceFile, InventoryHandle) == 212) ? 1 : -1];
#endif

// gp-19960: the destructor counts each file whose hot-chunk entries it
// frees.
extern int32_t HotChunkFilesNeedUpdating;
// gp-19952.
extern bNode ResourceFileList;
// gp-19944: files asked for and not yet loaded.
extern int32_t NumResourcesBeingLoaded;

// _GLOBAL_$I$LoaderNull__FP6bChunk (0x00199a48, the demo's 0x00190040):
// the list made empty. It is the static constructor of the object
// bchunkload.c shares.
void resource_static_init(void);
// _GLOBAL_$D$LoaderNull__FP6bChunk (0x00199a38): every file left on the
// list unlinked and deleted, as bTList<ResourceFile>'s destructor
// (0x001999c8) does, loaded or not.
void resource_static_destruct(void);

// LoadResourceFile(const char *, ResourceFileType, int, void (*)(int),
// int), 0x00199640.
ResourceFile *load_resource_file(const char *name, int32_t type,
                                 int32_t flags, ResourceFileCallback cb,
                                 intptr_t param);
// LoadResourceFile(const char *, ResourceFileType, int, int,
// void (*)(int), int), 0x001996f0: HOTCHUNKABLE when `hot_chunkable`,
// and USE_TEMPORARY_MEMORY and FREE_AFTER_LOADING unless `keep`. Nothing
// calls it.
ResourceFile *load_resource_file_hot(const char *name, int32_t type,
                                     int32_t hot_chunkable, int32_t keep,
                                     ResourceFileCallback cb,
                                     intptr_t param);
// ChangeFilenameForHotChunking (0x00199720 and 0x00199a60): the name
// FindResourceFile knows the file by. The read already queued keeps the
// old one.
void change_filename_for_hot_chunking(ResourceFile *rf, const char *name);
// UnloadResourceFile (0x00199728).
void unload_resource_file(ResourceFile *rf);
// ServiceResourceLoading (0x00199788): the files still loading, after the
// callback that one may have run.
int32_t service_resource_loading(void);
// IsResourceLoadingComplete (0x00199818).
int32_t is_resource_loading_complete(void);
// FindResourceFile(const char *) (0x00199828) and
// FindResourceFile(ResourceFileType) (0x00199890).
ResourceFile *find_resource_file(const char *name);
ResourceFile *find_resource_file_by_type(int32_t type);
// ResourceFile::GetSize (0x001995e0): the bytes of the file's chunks at
// the top level whose id is `id`, or of all of them for 0, with how many
// into *count when it is not NULL. 0 for a file not resident.
int32_t resource_file_get_size(ResourceFile *rf, uint32_t id,
                               int32_t *count);
// GetResourceFileSize (0x001998c8): the same over every file of a type.
int32_t get_resource_file_size(int32_t type, uint32_t id, int32_t *count);

#endif
