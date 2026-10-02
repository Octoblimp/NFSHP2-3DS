// resource -- see resource.h.

#include "resource.h"

#include <string.h>

#include "bchunk.h"
#include "bchunkload.h"
#include "bfile.h"
#include "bmem.h"
#include "eview.h"
#include "lzc.h"
#include "queuedfile.h"

#define COMP_MAGIC        0x504d4f43u   // "COMP"
#define RF_PRIORITY       5
#define RF_BLOCK_SIZE     0x02000000

int32_t HotChunkFilesNeedUpdating;
bNode ResourceFileList;
int32_t NumResourcesBeingLoaded;

static void unlink_file(ResourceFile *rf)
{
    bNode *next = rf->Node.next;
    bNode *prev = rf->Node.prev;

    prev->next = next;
    next->prev = prev;
}

// bStrCpy as far as the field holds, with nothing after the terminator.
static void copy_name(char *dst, size_t cap, const char *src)
{
    size_t i;

    for (i = 0; i + 1 < cap && src[i] != '\0'; i++)
        dst[i] = src[i];
    dst[i] = '\0';
}

// The image's bStrNCpy (0x002535a0): up to n bytes, stopping after the
// terminator, and no terminator when n runs out first.
static void b_strncpy(char *dst, const char *src, int32_t n)
{
    int32_t i;

    for (i = 0; i < n; i++) {
        dst[i] = src[i];
        if (src[i] == '\0')
            break;
    }
}

// AllocateMemory (0x00199408). bMalloc's 0x40 is a 128-byte boundary, as
// LoadChunks needs, and 8 is the top of the pool.
static void allocate_memory(ResourceFile *rf, int32_t top)
{
    int pool = (rf->Flags & RESOURCE_FILE_FLAG_USE_TEMPORARY_MEMORY) ? 72 : 64;

    if (top)
        pool |= 8;
    rf->pFirstChunk = (uint8_t *)bMalloc(rf->SizeofChunks, rf->Filename, 0,
                                         pool);
}

// FileTransferCallback (0x001995d0).
static void file_transfer_callback(intptr_t param, int32_t error)
{
    (void)error;
    ((ResourceFile *)param)->FileTransfersInProgress--;
}

// ResourceFile(const char *, ResourceFileType, int, void (*)(int), int),
// 0x00199320.
static ResourceFile *construct(ResourceFile *rf, const char *name,
                               int32_t type, int32_t flags,
                               ResourceFileCallback cb, intptr_t param)
{
    rf->Type = type;
    rf->Flags = flags;
    copy_name(rf->Filename, sizeof rf->Filename, name);
    rf->Callback = cb;
    rf->CallbackParam = param;
    rf->FileTransfersInProgress = 0;
    rf->LoadingFinishedFlag = 0;
    rf->HotFileNumber = 0;
    rf->pLoadedHotFileEntries = NULL;
    rf->NumLoadedHotFileEntries = 0;
    rf->InventoryHandle = 0;
    rf->HotFilename[0] = '\0';
    rf->SizeofChunks = bFileSizeName(rf->Filename);
    if (rf->SizeofChunks < 0)
        rf->SizeofChunks = 0;
    rf->pFirstChunk = NULL;
    if (rf->SizeofChunks != 0) {
        allocate_memory(rf, rf->Flags & RESOURCE_FILE_FLAG_LZCOMPRESSED);
        rf->FileTransfersInProgress++;
        change_queued_file_params(
            add_queued_file(rf->pFirstChunk, rf->Filename, 0,
                            rf->SizeofChunks, file_transfer_callback,
                            (intptr_t)rf),
            RF_PRIORITY, RF_BLOCK_SIZE);
    }
    return rf;
}

// ~ResourceFile (0x00199458), and the delete after it.
static void delete_file(ResourceFile *rf)
{
    if (gEWaitUntilRenderingDoneFn != NULL)
        gEWaitUntilRenderingDoneFn();
    if (rf->pLoadedHotFileEntries != NULL) {
        bFree(rf->pLoadedHotFileEntries);
        rf->NumLoadedHotFileEntries = 0;
        rf->pLoadedHotFileEntries = NULL;
        HotChunkFilesNeedUpdating++;
    }
    if (rf->pFirstChunk != NULL) {
        unload_chunks(rf->pFirstChunk, rf->SizeofChunks);
        bFree(rf->pFirstChunk);
        rf->pFirstChunk = NULL;
        post_load_fixup();
    }
    bFree(rf);
}

// LoadResourceIfFileTransferFinished (0x001994f0).
static void load_if_transfer_finished(ResourceFile *rf)
{
    if (rf->LoadingFinishedFlag || rf->FileTransfersInProgress != 0)
        return;
    if (rf->Flags & RESOURCE_FILE_FLAG_LZCOMPRESSED) {
        uint8_t *packed = rf->pFirstChunk;

        if (packed != NULL && bchunk_u32(packed) == COMP_MAGIC) {
            int32_t packed_size = rf->SizeofChunks;

            rf->pFirstChunk = NULL;
            rf->SizeofChunks = (int32_t)bchunk_u32(packed + 8);
            if (rf->SizeofChunks != 0) {
                allocate_memory(rf, 0);
                (void)lzc_decompress_into(packed, (size_t)packed_size, 0,
                                          rf->pFirstChunk,
                                          (size_t)rf->SizeofChunks, NULL);
            }
            bFree(packed);
        }
    }
    load_chunks(rf->pFirstChunk, rf->SizeofChunks);
    if (rf->Flags & RESOURCE_FILE_FLAG_FREE_AFTER_LOADING) {
        if (rf->pFirstChunk != NULL)
            bFree(rf->pFirstChunk);
        rf->pFirstChunk = NULL;
        rf->SizeofChunks = 0;
    }
    post_load_fixup();
    rf->LoadingFinishedFlag = 1;
}

void resource_static_init(void)
{
    ResourceFileList.prev = &ResourceFileList;
    ResourceFileList.next = &ResourceFileList;
}

void resource_static_destruct(void)
{
    while (ResourceFileList.next != &ResourceFileList) {
        ResourceFile *rf = (ResourceFile *)ResourceFileList.next;

        unlink_file(rf);
        delete_file(rf);
    }
}

ResourceFile *load_resource_file(const char *name, int32_t type,
                                 int32_t flags, ResourceFileCallback cb,
                                 intptr_t param)
{
    ResourceFile *rf;
    bNode *last;

    NumResourcesBeingLoaded++;
    rf = construct((ResourceFile *)bMalloc((int)sizeof(ResourceFile),
                                           "ResourceFile", 0, 16),
                   name, type, flags, cb, param);
    last = ResourceFileList.prev;
    last->next = &rf->Node;
    ResourceFileList.prev = &rf->Node;
    rf->Node.prev = last;
    rf->Node.next = &ResourceFileList;
    return rf;
}

ResourceFile *load_resource_file_hot(const char *name, int32_t type,
                                     int32_t hot_chunkable, int32_t keep,
                                     ResourceFileCallback cb,
                                     intptr_t param)
{
    int32_t flags = hot_chunkable != 0;

    if (!keep)
        flags |= RESOURCE_FILE_FLAG_USE_TEMPORARY_MEMORY
                 | RESOURCE_FILE_FLAG_FREE_AFTER_LOADING;
    return load_resource_file(name, type, flags, cb, param);
}

void change_filename_for_hot_chunking(ResourceFile *rf, const char *name)
{
    b_strncpy(rf->Filename, name, 79);
}

void unload_resource_file(ResourceFile *rf)
{
    while (!rf->LoadingFinishedFlag)
        service_resource_loading();
    unlink_file(rf);
    delete_file(rf);
}

int32_t service_resource_loading(void)
{
    bNode *n;

    service_queued_files();
    if (NumResourcesBeingLoaded == 0)
        return 0;
    for (n = ResourceFileList.next; n != &ResourceFileList; n = n->next) {
        ResourceFile *rf = (ResourceFile *)n;

        if (rf->LoadingFinishedFlag)
            continue;
        load_if_transfer_finished(rf);
        if (!rf->LoadingFinishedFlag)
            return NumResourcesBeingLoaded;
        NumResourcesBeingLoaded--;
        if (rf->Callback != NULL)
            rf->Callback(rf->CallbackParam);
        return NumResourcesBeingLoaded;
    }
    return 0;
}

int32_t is_resource_loading_complete(void)
{
    return NumResourcesBeingLoaded == 0;
}

ResourceFile *find_resource_file(const char *name)
{
    bNode *n;

    for (n = ResourceFileList.prev; n != &ResourceFileList; n = n->prev) {
        if (strcmp(((ResourceFile *)n)->Filename, name) == 0)
            return (ResourceFile *)n;
    }
    return NULL;
}

ResourceFile *find_resource_file_by_type(int32_t type)
{
    bNode *n;

    for (n = ResourceFileList.prev; n != &ResourceFileList; n = n->prev) {
        if (((ResourceFile *)n)->Type == type)
            return (ResourceFile *)n;
    }
    return NULL;
}

int32_t resource_file_get_size(ResourceFile *rf, uint32_t id,
                               int32_t *count)
{
    int32_t  total = 0;
    int32_t  n = 0;
    uint8_t *c = rf->pFirstChunk;

    if (c != NULL) {
        uint8_t *end = c + rf->SizeofChunks;

        while (c != end) {
            uint32_t size = bchunk_u32(c + 4);

            if (id == 0 || bchunk_u32(c) == id) {
                n++;
                total += (int32_t)size;
            }
            c += size + 8;
        }
    }
    if (count != NULL)
        *count = n;
    return total;
}

int32_t get_resource_file_size(int32_t type, uint32_t id, int32_t *count)
{
    int32_t total = 0;
    int32_t chunks = 0;
    bNode  *n;

    for (n = ResourceFileList.prev; n != &ResourceFileList; n = n->prev) {
        ResourceFile *rf = (ResourceFile *)n;
        int32_t       k;

        if (rf->Type != type)
            continue;
        total += resource_file_get_size(rf, id, &k);
        chunks += k;
    }
    if (count != NULL)
        *count = chunks;
    return total;
}
