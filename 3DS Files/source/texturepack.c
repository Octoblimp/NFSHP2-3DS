// texturepack -- see texturepack.h.

#include "texturepack.h"

#include <stdio.h>
#include <string.h>

#include "bchunk.h"
#include "bmem.h"
#include "eefpu.h"
#include "esolid.h"
#include "realtime.h"

#define TEXTURE_PACK_ID         0xb0300001u
#define TEXTURE_ANIM_PACK_ID    0xb0300100u

// The texture GetTextureInfo falls back on.
#define DEFAULT_TEXTURE_HASH    0x19006835u

// 1/60, the float at 0x0032185c (gp-29588): 0x3c888889.
#define SECONDS_PER_FRAME       0x1.111112p-6f

bNode TexturePackList = { &TexturePackList, &TexturePackList };
bNode TextureAnimPackList = { &TextureAnimPackList, &TextureAnimPackList };

int32_t TweakFPS;
int32_t texturepack_breaks;

TextureInfo *(*gERenderTargetTextureInfoFn)(uint32_t name_hash);
void (*gServiceQueuedFilesFn)(void);

static uint8_t *next_chunk(uint8_t *c)
{
    return c + 8 + bchunk_u32(c + 4);
}

// The R5900's addu, which wraps.
static int32_t add32(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)a + (uint32_t)b);
}

// The R5900's div's remainder. Only 0x80000000 by -1 would trap in C;
// the EE's is 0.
static int32_t rem32(int32_t a, int32_t b)
{
    if (b == -1)
        return 0;
    return a % b;
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

// ------------------------------------------------------------ the loader

int loader_texture_pack(uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);

    if (type == TEXTURE_PACK_ID) {
        uint8_t *head = chunk + 8;
        uint8_t *table = next_chunk(head);
        uint8_t *blob = next_chunk(table);
        TexturePackHeader *h = (TexturePackHeader *)(void *)(head + 8);
        uint8_t *payload = blob + 8;
        // The placements count from the payload rounded up to 128.
        uint8_t *data = (uint8_t *)(((uintptr_t)payload + 127u)
                                    & ~(uintptr_t)127u);
        int32_t size = (int32_t)bchunk_u32(blob + 4)
                       - (int32_t)(data - payload);
        int32_t num = (int32_t)(bchunk_u32(table + 4)
                                / (uint32_t)sizeof(TextureInfo));
        TexturePack *p = (TexturePack *)bMalloc((int)sizeof(TexturePack),
                                                "TexturePack", 0, 16);

        p = texturepack_construct(p, h->Name, h->Filename);
        h->pTexturePack = p;
        texturepack_attach_texture_table(
            p, (TextureInfo *)(void *)(table + 8), num);
        texturepack_assign_texture_data(p, data, 0, size);
        return 1;
    }
    if (type == TEXTURE_ANIM_PACK_ID) {
        uint8_t *head = chunk + 8;
        uint8_t *anims = next_chunk(head);
        uint8_t *entries = next_chunk(anims);
        TextureAnimPackHeader *h = (TextureAnimPackHeader *)(void *)(head + 8);

        if (h->Version == 1) {
            TextureAnimPack *p = (TextureAnimPack *)bMalloc(
                (int)sizeof(TextureAnimPack), "TextureAnimPack", 0, 16);

            p = textureanimpack_construct(
                p, (TextureAnim *)(void *)(anims + 8),
                (TextureAnimEntry *)(void *)(entries + 8),
                (int32_t)(bchunk_u32(anims + 4)
                          / (uint32_t)sizeof(TextureAnim)),
                (int32_t)(bchunk_u32(entries + 4)
                          / (uint32_t)sizeof(TextureAnimEntry)));
            h->pTextureAnimPack = p;
            textureanimpack_init_anims(p);
        } else {
            h->pTextureAnimPack = NULL;
        }
        return 1;
    }
    return 0;
}

int unloader_texture_pack(uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);

    // Neither clears the header's pointer.
    if (type == TEXTURE_PACK_ID) {
        TexturePackHeader *h = (TexturePackHeader *)(void *)(chunk + 16);

        if (h->pTexturePack != NULL)
            texturepack_destruct(h->pTexturePack, 3);
        return 1;
    }
    if (type == TEXTURE_ANIM_PACK_ID) {
        TextureAnimPackHeader *h = (TextureAnimPackHeader *)(void *)(chunk + 16);

        if (h->Version == 1 && h->pTextureAnimPack != NULL)
            textureanimpack_destruct(h->pTextureAnimPack, 3);
        return 1;
    }
    return 0;
}

// ----------------------------------------------------------- TexturePack

TexturePack *texturepack_construct(TexturePack *p, const char *name,
                                   const char *filename)
{
    // Name and Filename, which lie end to end, and the 32 bytes after
    // them: what the two copies below write, as the console's memory has it.
    char run[128];
    char buf[1024];
    int i;

    p->LoadedTextureDataList.next = &p->LoadedTextureDataList;
    p->LoadedTextureDataList.prev = &p->LoadedTextureDataList;
    // bStrCpy copies to the NUL: the name into Name and on into Filename,
    // then Filename is emptied and the file name copied over it, on into
    // the fields after it. The loader gives the header's name and file
    // name, which lie end to end too, then the pack's pointer, then the
    // table's type, 0x30300003, whose second byte is 0. So no name the
    // loader gives runs past 85 characters, nor a file name past 69: both
    // copies stop short of LoadedTextureDataList, the one field set before
    // them, and all they write past Filename is set again below. Name's
    // hash reads on into Filename when Name has no NUL.
    memcpy(run, p->Name, sizeof p->Name + sizeof p->Filename);
    for (i = 0; name[i] != 0 && i < (int)sizeof run - 1; i++)
        run[i] = name[i];
    run[i] = 0;
    run[sizeof p->Name] = 0;
    if (filename != NULL) {
        char *f = run + sizeof p->Name;

        for (i = 0; filename[i] != 0 && f + i < run + sizeof run - 1; i++)
            f[i] = filename[i];
        f[i] = 0;
    }
    memcpy(p->Name, run, sizeof p->Name);
    memcpy(p->Filename, run + sizeof p->Name, sizeof p->Filename);
    p->NameHash = bchunk_hash(run);
    p->pTextureInfo = NULL;
    p->NumTextures = 0;
    p->pTextureInfoNeedsToBeFreed = 0;
    p->TextureDataFilePos = 0;
    p->CurrentLoadingTextureData = NULL;
    p->NumNotYetLoadedTextureDatas = 0;
    p->MemoryPool = 64;
    link_tail(&TexturePackList, &p->Node);
    // bAddCodeineInventory(0, name, ...) tells the debugger's channel, which
    // the port does not have, and returns the name's hash. Name is read as
    // the console reads it, on through Filename to a NUL.
    snprintf(buf, sizeof buf, "TexturePack,%s", p->Name);
    p->InventoryHandle = (int32_t)bchunk_hash(buf);
    return p;
}

// ~LoadedTextureData, 0x001a2eb8.
static void loadedtexturedata_destruct(LoadedTextureData *d, int32_t flags)
{
    if (d->Buf != NULL)
        bFree(d->Buf);
    if (flags & 1)
        bFree(d);
}

void texturepack_destruct(TexturePack *p, int32_t flags)
{
    bNode *n;

    // The streaming half's load in flight. With no ServiceQueuedFiles to
    // finish it, there is nothing to wait for.
    while (p->CurrentLoadingTextureData != NULL
           && gServiceQueuedFilesFn != NULL)
        gServiceQueuedFilesFn();
    if (p->pTextureInfoNeedsToBeFreed) {
        bFree(p->pTextureInfo);
        p->pTextureInfo = NULL;
    }
    list_unlink(&p->Node);
    // bRemoveCodeineInventory only tells the debugger's channel.
    while ((n = p->LoadedTextureDataList.next) != &p->LoadedTextureDataList) {
        list_unlink(n);
        loadedtexturedata_destruct((LoadedTextureData *)(void *)n, 3);
    }
    if (flags & 1)
        bFree(p);
}

void texturepack_attach_texture_table(TexturePack *p, TextureInfo *table,
                                      int32_t num)
{
    TextureInfo *t = table;
    int32_t n;

    p->pTextureInfo = table;
    p->NumTextures = num;
    // The demo asked GetTextureInfo for each record here and dropped the
    // answer, which moved the pack that had it to the list's head; retail
    // does not ask.
    for (n = num; n > 0; n--, t++) {
        if (t->ImageParentHash != 0)
            t->pImageParent = texturepack_get_texture(p, t->ImageParentHash);
        else
            t->pImageParent = t;
        t->pTexturePack = p;
        t->ImageData = NULL;
        t->PaletteData = NULL;
        t->pActiveTexture = NULL;
        t->PaletteVramAddress = 0;
        t->ImageVramAddress = 0;
    }
    eDirtyTextures = 1;
}

void texturepack_assign_texture_data(TexturePack *p, uint8_t *data,
                                     int32_t pos, int32_t size)
{
    int32_t end = add32(pos, size);
    int32_t i;

    for (i = 0; i < p->NumTextures; i++) {
        TextureInfo *t = &p->pTextureInfo[i];

        if (t->ImageSize != 0 && t->ImagePlacement >= pos
            && t->ImagePlacement < end)
            t->ImageData = data + (t->ImagePlacement - pos);
        if (t->PaletteSize != 0 && t->PalettePlacement >= pos
            && t->PalettePlacement < end)
            t->PaletteData = data + (t->PalettePlacement - pos);
    }
    eDirtyTextures = 1;
}

void texturepack_unassign_texture_data(TexturePack *p, int32_t pos,
                                       int32_t size)
{
    int32_t end = add32(pos, size);
    int32_t i;

    for (i = 0; i < p->NumTextures; i++) {
        TextureInfo *t = &p->pTextureInfo[i];

        if (t->ImageSize != 0 && t->ImagePlacement >= pos
            && t->ImagePlacement < end)
            t->ImageData = NULL;
        if (t->PaletteSize != 0 && t->PalettePlacement >= pos
            && t->PalettePlacement < end)
            t->PaletteData = NULL;
    }
    eDirtyTextures = 1;
}

TextureInfo *texturepack_get_loaded_texture(TexturePack *p, uint32_t hash)
{
    int32_t i;

    for (i = 0; i < p->NumTextures; i++) {
        TextureInfo *t = &p->pTextureInfo[i];

        if (t->NameHash == hash && t->ImageData != NULL
            && (t->PaletteSize == 0 || t->PaletteData != NULL))
            return t;
    }
    return NULL;
}

TextureInfo *texturepack_get_texture(TexturePack *p, uint32_t hash)
{
    int32_t i;

    for (i = 0; i < p->NumTextures; i++) {
        if (p->pTextureInfo[i].NameHash == hash)
            return &p->pTextureInfo[i];
    }
    return NULL;
}

TextureInfo *texturepack_get_nth_texture(TexturePack *p, int32_t n)
{
    if (n < p->NumTextures)
        return &p->pTextureInfo[n];
    return NULL;
}

// ------------------------------------------------------- the lookups

TextureInfo *GetTextureInfo(uint32_t hash, int use_default,
                            int include_unloaded)
{
    bNode *n;
    TextureInfo *t;

    for (n = TexturePackList.next; n != &TexturePackList; n = n->next) {
        TexturePack *p = (TexturePack *)(void *)n;

        t = include_unloaded ? texturepack_get_texture(p, hash)
                             : texturepack_get_loaded_texture(p, hash);
        if (t != NULL) {
            // The pack that had it goes to the head, so it is asked first
            // next time.
            list_unlink(n);
            n->next = TexturePackList.next;
            TexturePackList.next->prev = n;
            TexturePackList.next = n;
            n->prev = &TexturePackList;
            t->UsedFlag = 1;
            return t;
        }
    }
    t = gERenderTargetTextureInfoFn != NULL
        ? gERenderTargetTextureInfoFn(hash) : NULL;
    if (t != NULL)
        return t;
    if (!use_default)
        return NULL;
    t = GetTextureInfo(DEFAULT_TEXTURE_HASH, 0, 0);
    if (t != NULL)
        return t;
    texturepack_breaks++;
    return NULL;
}

void *texturepack_get_texture_info(uint32_t hash, int use_default,
                                   int include_unloaded)
{
    return GetTextureInfo(hash, use_default, include_unloaded);
}

TextureInfo *GetNthTextureInfo(int32_t n)
{
    bNode *node;

    for (node = TexturePackList.next; node != &TexturePackList;
         node = node->next) {
        TexturePack *p = (TexturePack *)(void *)node;

        if (n < p->NumTextures)
            return texturepack_get_nth_texture(p, n);
        n -= p->NumTextures;
    }
    return NULL;
}

void MaybePrintUnusedTextures(void)
{
}

// ------------------------------------------------------------- the names

int RenameTextureInfo(uint32_t hash, const char *name)
{
    TextureInfo *t = GetTextureInfo(hash, 0, 1);

    if (t == NULL)
        return 0;
    // A bMemCpy of 24 bytes: `name` must have that many to read, NUL or
    // not. A name with no NUL in them hashes on into NameHash.
    memcpy(t->DebugName, name, sizeof t->DebugName);
    t->NameHash = bchunk_hash(t->DebugName);
    return 1;
}

int SwapTextureInfoNames(uint32_t a, uint32_t b)
{
    TextureInfo *x = GetTextureInfo(a, 0, 1);
    TextureInfo *y = GetTextureInfo(b, 0, 1);
    char name[sizeof x->DebugName];

    if (x == NULL || y == NULL)
        return 0;
    memcpy(name, x->DebugName, sizeof name);
    // The two can be one texture.
    memmove(x->DebugName, y->DebugName, sizeof name);
    x->NameHash = bchunk_hash(x->DebugName);
    memcpy(y->DebugName, name, sizeof name);
    y->NameHash = bchunk_hash(y->DebugName);
    return 1;
}

// ------------------------------------------------------ TextureAnimPack

TextureAnimPack *textureanimpack_construct(TextureAnimPack *p,
                                           TextureAnim *anims,
                                           TextureAnimEntry *entries,
                                           int32_t num_anims,
                                           int32_t num_entries)
{
    TextureAnimEntry *e = entries;
    int32_t i;

    p->NumTextureAnimEntries = num_entries;
    p->TextureAnimTable = anims;
    p->TextureAnimEntryTable = entries;
    p->NumTextureAnims = num_anims;
    // Each flipbook's frames follow the last one's.
    for (i = 0; i < num_anims; i++) {
        anims[i].TextureAnimTable = e;
        e += anims[i].NumFrames;
    }
    link_tail(&TextureAnimPackList, &p->Node);
    return p;
}

void textureanimpack_destruct(TextureAnimPack *p, int32_t flags)
{
    list_unlink(&p->Node);
    if (flags & 1)
        bFree(p);
}

void textureanimpack_init_anims(TextureAnimPack *p)
{
    int32_t i, k;

    for (i = 0; i < p->NumTextureAnims; i++) {
        TextureAnim *a = &p->TextureAnimTable[i];
        int32_t valid = 1;

        for (k = 0; k < a->NumFrames; k++) {
            TextureAnimEntry *e = &a->TextureAnimTable[k];
            TextureInfo *t = GetTextureInfo(e->NameHash, 0, 0);

            if (t != NULL) {
                e->pTextureInfo = t;
                e->OriginalImageData = t->ImageData;
                e->OriginalPaletteData = t->PaletteData;
            } else {
                valid = 0;
                e->pTextureInfo = NULL;
                e->OriginalImageData = NULL;
                e->OriginalPaletteData = NULL;
            }
        }
        a->Valid = valid;
        a->CurrentFrame = 0;
    }
}

void UpdateTextureAnimations(void)
{
    float world = (float)WorldTimeFrames * SECONDS_PER_FRAME;
    float real = (float)RealTimeFrames * SECONDS_PER_FRAME;
    int32_t tweak = TweakFPS;
    bNode *node;

    for (node = TextureAnimPackList.next; node != &TextureAnimPackList;
         node = node->next) {
        TextureAnimPack *p = (TextureAnimPack *)(void *)node;
        int32_t i;

        for (i = 0; i < p->NumTextureAnims; i++) {
            TextureAnim *a = &p->TextureAnimTable[i];
            int32_t n = a->NumFrames;
            int32_t fps, frame, k;
            float t;

            if (!a->Valid)
                continue;
            t = a->TimeBase == 1 ? real : world;
            fps = tweak != 0 ? tweak : a->FramesPerSecond;
            if (n == 0)
                continue;
            frame = rem32(ee_trunc_w((float)fps * t), n);
            if (frame == a->CurrentFrame)
                continue;
            a->CurrentFrame = frame;
            // Frame k shows the pixels frame k + frame had to begin with.
            for (k = 0; k < n; k++) {
                TextureAnimEntry *src =
                    &a->TextureAnimTable[rem32(add32(k, frame), n)];
                TextureInfo *dst = a->TextureAnimTable[k].pTextureInfo;

                dst->PaletteData = src->OriginalPaletteData;
                dst->ImageData = src->OriginalImageData;
            }
        }
    }
}

TextureAnim *GetTextureAnim(uint32_t hash)
{
    bNode *node;

    for (node = TextureAnimPackList.next; node != &TextureAnimPackList;
         node = node->next) {
        TextureAnimPack *p = (TextureAnimPack *)(void *)node;
        int32_t i;

        for (i = 0; i < p->NumTextureAnims; i++) {
            if (p->TextureAnimTable[i].NameHash == hash)
                return &p->TextureAnimTable[i];
        }
    }
    return NULL;
}
