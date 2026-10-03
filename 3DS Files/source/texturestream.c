// texturestream -- see texturestream.h.

#include "texturestream.h"

#include <stddef.h>
#include <string.h>

#include "bchunk.h"
#include "bfile.h"
#include "bmem.h"
#include "esolid.h"
#include "eview.h"
#include "queuedfile.h"

// The most of a pack's file LoadTextureTableFromFile reads: its header
// and table must lie in the first 128 KB.
#define TABLE_READ_MAX  0x20000

// A record on the disc: the image's TextureInfo.
#define DISC_RECORD     164

// How far apart two ranges still are neighbours.
#define NEIGHBOUR_GAP   1024

TexturePack *pDynamicTexturePack;

typedef char texturestream_info_check[
    (offsetof(TextureInfo, pTexturePack) - offsetof(TextureInfo, DebugName)
     == 128) ? 1 : -1];

// The R5900's addu and subu, which wrap.
static int32_t add32(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)a + (uint32_t)b);
}

static int32_t sub32(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)a - (uint32_t)b);
}

static void link_tail(bNode *list, bNode *n)
{
    bNode *last = list->prev;

    last->next = n;
    list->prev = n;
    n->prev = last;
    n->next = list;
}

static void list_unlink(bNode *n)
{
    n->prev->next = n->next;
    n->next->prev = n->prev;
}

static LoadedTextureData *ltd(bNode *n)
{
    return (LoadedTextureData *)(void *)n;
}

// A disc record into the port's TextureInfo. The image copies the table
// with one bMemCpy, and on the 3DS this is that copy, field for field; the
// host that runs the checker has wider pointers, and gets the same table.
static void record_from_disc(TextureInfo *t, const uint8_t *d)
{
    t->Node.next = (bNode *)(uintptr_t)bchunk_u32(d);
    t->Node.prev = (bNode *)(uintptr_t)bchunk_u32(d + 4);
    // DebugName to ScrollTimeStep, 128 bytes.
    memcpy((uint8_t *)t + offsetof(TextureInfo, DebugName), d + 8, 128);
    t->pTexturePack = (TexturePack *)(uintptr_t)bchunk_u32(d + 136);
    t->pImageParent = (TextureInfo *)(uintptr_t)bchunk_u32(d + 140);
    t->ImageData = (uint8_t *)(uintptr_t)bchunk_u32(d + 144);
    t->PaletteData = (uint8_t *)(uintptr_t)bchunk_u32(d + 148);
    t->pActiveTexture = (void *)(uintptr_t)bchunk_u32(d + 152);
    t->pStackedActiveTexture = (void *)(uintptr_t)bchunk_u32(d + 156);
    memcpy(&t->PaletteVramAddress, d + 160, 2);
    memcpy(&t->ImageVramAddress, d + 162, 2);
}

void texturepack_load_texture_table_from_file(TexturePack *p,
                                              const char *filename)
{
    bFile    *f;
    uint8_t  *buf;
    TextureInfo *table;
    int32_t   n, num, i;
    uint32_t  tab, blob;

    // bStrCpy, to the NUL. Every caller's name is far shorter than
    // Filename; the port stops one short of its end.
    for (i = 0; filename[i] != 0 && i < (int32_t)sizeof p->Filename - 1; i++)
        p->Filename[i] = filename[i];
    p->Filename[i] = 0;
    f = bOpen(filename);
    if (f == NULL)
        return;
    n = bFileSize(f);
    if (n >= TABLE_READ_MAX)
        n = TABLE_READ_MAX;
    buf = (uint8_t *)bMalloc(n, "TextureTable", 0, 72);
    bRead(f, buf, n);
    bClose(f);
    // The pack chunk's first child is its header, its second the table,
    // its third the blob: each offset here counts from buf.
    tab = 16 + bchunk_u32(buf + 12);
    blob = tab + 8 + bchunk_u32(buf + tab + 4);
    if ((uint32_t)n >= blob) {
        // The blob's payload, rounded up to 128 as the image rounds it:
        // on the address, which bMalloc's 0x40 has made a multiple of 128.
        uintptr_t data = (uintptr_t)buf + blob + 8;

        p->TextureDataFilePos = (int32_t)(((data + 127) & ~(uintptr_t)127)
                                          - (uintptr_t)buf);
        num = (int32_t)(bchunk_u32(buf + tab + 4) / DISC_RECORD);
        table = (TextureInfo *)bMalloc(num * (int)sizeof(TextureInfo),
                                       p->Name, 0, 16);
        for (i = 0; i < num; i++)
            record_from_disc(&table[i], buf + tab + 8 + DISC_RECORD * i);
        texturepack_attach_texture_table(p, table, num);
        p->pTextureInfoNeedsToBeFreed = 1;
    }
    bFree(buf);
}

LoadedTextureData *texturepack_find_loaded_texture_data(TexturePack *p,
                                                        int32_t pos,
                                                        int32_t size)
{
    int32_t end = add32(pos, size);
    bNode *n;

    for (n = p->LoadedTextureDataList.next; n != &p->LoadedTextureDataList;
         n = n->next) {
        LoadedTextureData *d = ltd(n);

        if (d->LowPos <= pos && end <= d->HighPos)
            return d;
    }
    return NULL;
}

LoadedTextureData *texturepack_find_not_yet_loaded_neighbour_texture_data(
    TexturePack *p, int32_t pos, int32_t size)
{
    int32_t end = add32(pos, size);
    bNode *n;

    for (n = p->LoadedTextureDataList.next; n != &p->LoadedTextureDataList;
         n = n->next) {
        LoadedTextureData *d = ltd(n);

        if (d->Buf != NULL)
            continue;
        // Ends at most 1 KB before it, or starts at most 1 KB after it.
        if (end >= add32(d->LowPos, -NEIGHBOUR_GAP) && end <= d->LowPos)
            return d;
        if (pos <= add32(d->HighPos, NEIGHBOUR_GAP) && pos >= d->HighPos)
            return d;
    }
    return NULL;
}

// The list's order, 0x001ac850: by where each range starts, but a
// callback's range is in order with anything.
static int32_t in_order(bNode *a, bNode *b)
{
    if (ltd(a)->Callback != NULL || ltd(b)->Callback != NULL)
        return 1;
    return ltd(a)->LowPos <= ltd(b)->LowPos;
}

void texturepack_add_loaded_texture_data(TexturePack *p, int32_t pos,
                                         int32_t size)
{
    LoadedTextureData *d, *m;
    int32_t end = add32(pos, size);

    d = texturepack_find_loaded_texture_data(p, pos, size);
    if (d != NULL) {
        d->NumAssignments++;
        return;
    }
    d = texturepack_find_not_yet_loaded_neighbour_texture_data(p, pos, size);
    if (d != NULL) {
        if (pos < d->LowPos)
            d->LowPos = pos;
        if (d->HighPos < end)
            d->HighPos = end;
        d->NumAssignments++;
        // Grown, it may reach a second: the two become one.
        m = texturepack_find_not_yet_loaded_neighbour_texture_data(
            p, d->LowPos, sub32(d->HighPos, d->LowPos));
        if (m == NULL)
            return;
        if (m->LowPos < d->LowPos)
            d->LowPos = m->LowPos;
        if (d->HighPos < m->HighPos)
            d->HighPos = m->HighPos;
        d->NumAssignments += m->NumAssignments;
        list_unlink(&m->Node);
        loadedtexturedata_destruct(m, 3);
        p->NumNotYetLoadedTextureDatas--;
        return;
    }
    // A new range. CallbackParam is left as the heap had it.
    d = (LoadedTextureData *)bMalloc((int)sizeof *d, "LoadedTextureData", 0,
                                     16);
    d->HighPos = end;
    d->MemoryPool = p->MemoryPool;
    d->NumAssignments = 1;
    d->LowPos = pos;
    d->LoadingCompleted = 0;
    d->LoadingInProgress = 0;
    link_tail(&p->LoadedTextureDataList, &d->Node);
    p->NumNotYetLoadedTextureDatas++;
    d->Buf = NULL;
    d->Callback = NULL;
    blist_sort(&p->LoadedTextureDataList, in_order);
}

int32_t texturepack_remove_loaded_texture_data(TexturePack *p, int32_t pos,
                                               int32_t size)
{
    LoadedTextureData *d = texturepack_find_loaded_texture_data(p, pos, size);

    if (d == NULL)
        return 0;
    if (--d->NumAssignments == 0 && !d->LoadingInProgress)
        texturepack_delete_loaded_texture_data(p, d);
    return 1;
}

void texturepack_delete_loaded_texture_data(TexturePack *p,
                                            LoadedTextureData *d)
{
    if (d->LoadingCompleted)
        texturepack_unassign_texture_data(p, d->LowPos,
                                          sub32(d->HighPos, d->LowPos));
    else
        p->NumNotYetLoadedTextureDatas--;
    if (gEWaitUntilRenderingDoneFn != NULL)
        gEWaitUntilRenderingDoneFn();
    list_unlink(&d->Node);
    loadedtexturedata_destruct(d, 3);
}

void texturepack_load_texture_from_file(TexturePack *p, TextureInfo *t)
{
    if (t->ImageSize != 0)
        texturepack_add_loaded_texture_data(p, t->ImagePlacement,
                                            t->ImageSize);
    if (t->PaletteSize != 0)
        texturepack_add_loaded_texture_data(p, t->PalettePlacement,
                                            t->PaletteSize);
}

void texturepack_unload_texture_from_file(TexturePack *p, TextureInfo *t)
{
    if (t->ImageSize != 0)
        texturepack_remove_loaded_texture_data(p, t->ImagePlacement,
                                               t->ImageSize);
    if (t->PaletteSize != 0)
        texturepack_remove_loaded_texture_data(p, t->PalettePlacement,
                                               t->PaletteSize);
}

void texturepack_load_textures_from_file(TexturePack *p, uint32_t *hashes,
                                         int n, LoadedTextureDataCallback cb,
                                         intptr_t param)
{
    LoadedTextureData *d;

    for (; n > 0; n--, hashes++) {
        TextureInfo *t = *hashes != 0 ? texturepack_get_texture(p, *hashes)
                                      : NULL;

        if (t != NULL)
            texturepack_load_texture_from_file(p, t);
    }
    if (cb != NULL) {
        // An empty range at the tail, unsorted.
        d = (LoadedTextureData *)bMalloc((int)sizeof *d, "LoadedTextureData",
                                         0, 16);
        d->CallbackParam = param;
        d->MemoryPool = p->MemoryPool;
        d->LowPos = 0;
        d->HighPos = 0;
        d->NumAssignments = 0;
        d->LoadingCompleted = 0;
        d->LoadingInProgress = 0;
        link_tail(&p->LoadedTextureDataList, &d->Node);
        p->NumNotYetLoadedTextureDatas++;
        d->Callback = cb;
        d->Buf = NULL;
    }
    texturepack_service_loading_textures(p);
}

void texturepack_unload_textures_from_file(TexturePack *p, uint32_t *hashes,
                                           int n)
{
    for (; n > 0; n--, hashes++) {
        TextureInfo *t = *hashes != 0 ? texturepack_get_texture(p, *hashes)
                                      : NULL;

        if (t != NULL)
            texturepack_unload_texture_from_file(p, t);
    }
}

// 0x001ad608, QueuedFile's callback.
static void read_callback(intptr_t param, int32_t error)
{
    texturepack_read_callback((TexturePack *)param, error);
}

void texturepack_service_loading_textures(TexturePack *p)
{
    int32_t waiting;
    bNode *n;

    if (p->CurrentLoadingTextureData != NULL)
        return;
    waiting = p->NumNotYetLoadedTextureDatas;
    if (waiting == 0)
        return;
    for (n = p->LoadedTextureDataList.next; n != &p->LoadedTextureDataList;
         n = n->next) {
        LoadedTextureData *d = ltd(n);

        if (d->Buf != NULL)
            continue;
        if (d->HighPos == d->LowPos) {
            // A callback's range: everything before it is in. The image
            // adds one to the count it read on the way in, where taking
            // the range off would take one away.
            list_unlink(n);
            p->NumNotYetLoadedTextureDatas = waiting + 1;
            if (d->Callback != NULL)
                d->Callback(d->CallbackParam);
            loadedtexturedata_destruct(d, 3);
            texturepack_service_loading_textures(p);
            return;
        }
        d->LoadingInProgress = 1;
        p->CurrentLoadingTextureData = d;
        p->NumNotYetLoadedTextureDatas--;
        d->Buf = (uint8_t *)bMalloc(sub32(d->HighPos, d->LowPos),
                                    "LoadedTextureData", 0, d->MemoryPool);
        add_queued_file(d->Buf, p->Filename,
                        add32(p->TextureDataFilePos, d->LowPos),
                        sub32(d->HighPos, d->LowPos), read_callback,
                        (intptr_t)p);
        return;
    }
}

void texturepack_read_callback(TexturePack *p, int32_t error)
{
    LoadedTextureData *d = p->CurrentLoadingTextureData;

    (void)error;
    p->CurrentLoadingTextureData = NULL;
    texturepack_assign_texture_data(p, d->Buf, d->LowPos,
                                    sub32(d->HighPos, d->LowPos));
    d->LoadingInProgress = 0;
    d->LoadingCompleted = 1;
    efix_up_tables();
    if (d->NumAssignments == 0)
        texturepack_delete_loaded_texture_data(p, d);
    texturepack_service_loading_textures(p);
}

void texturepack_unload_all_textures_from_file(TexturePack *p)
{
    bNode *n = p->LoadedTextureDataList.next;

    while (n != &p->LoadedTextureDataList) {
        bNode *next = n->next;

        ltd(n)->NumAssignments = 0;
        if (!ltd(n)->LoadingInProgress)
            texturepack_delete_loaded_texture_data(p, ltd(n));
        n = next;
    }
    p->NumNotYetLoadedTextureDatas = 0;
}

int32_t texturepack_get_loaded_size(TexturePack *p)
{
    int32_t size = 0;
    bNode *n;

    for (n = p->LoadedTextureDataList.next; n != &p->LoadedTextureDataList;
         n = n->next)
        size = add32(size, sub32(ltd(n)->HighPos, ltd(n)->LowPos));
    return size;
}
