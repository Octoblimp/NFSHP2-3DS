// smokeableinfo -- the data side of Smokeable.obj: SmokeableInfoList and
// the spawners, chunk slot 27's loader and unloader, FindSmokeableInfo.
// See smokeable.h. Apart from smokeable.c so the loader table's harness
// can link it without the bodies.

#include "smokeable.h"

#include <stdint.h>

#include "bchunk.h"
#include "terraintype.h"

bNode             SmokeableInfoList = { &SmokeableInfoList, &SmokeableInfoList };
SmokeableSpawner *pSmokeableSpawners;
int32_t           NumSmokeableSpawners;

SmokeableSpawner *smokeable_get_spawner(int32_t i)
{
    if (i < 0)
        return NULL;
    return &pSmokeableSpawners[i];
}

int32_t smokeable_get_spawner_index(const SmokeableSpawner *s)
{
    if (s == NULL)
        return -1;
    return (int32_t)(s - pSmokeableSpawners);
}

void smokeableinfo_memory_image_load(SmokeableInfo *si)
{
    int32_t t = terrain_match_hash(si->TerrainTypeHash);

    si->AnchorEmitterList.next = &si->AnchorEmitterList;
    si->AnchorEmitterList.prev = &si->AnchorEmitterList;
    si->DynamicEmitterList.next = &si->DynamicEmitterList;
    si->TheTerrainType = t;
    si->DynamicEmitterList.prev = &si->DynamicEmitterList;
}

// The records start at the payload's first sixteen-byte boundary; the
// count is the rest of the payload over the record's size, unsigned.
static uint8_t *chunk_records(uint8_t *c, int32_t *n)
{
    uint8_t *data = (uint8_t *)(((uintptr_t)c + 23) & ~(uintptr_t)15);
    uint32_t used = (uint32_t)(data - (c + 8));

    *n = (int32_t)((bchunk_u32(c + 4) - used)
                   / (uint32_t)sizeof(SmokeableInfo));
    return data;
}

int smokeable_loader(uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);

    if (type == 0x00034026u) {
        int32_t  n, i, k;
        uint8_t *data = chunk_records(chunk, &n);
        bNode   *it;

        for (i = 0; i < n; i++) {
            SmokeableInfo *si =
                (SmokeableInfo *)(void *)(data + i * sizeof(SmokeableInfo));
            bNode *tail = SmokeableInfoList.prev;

            tail->next = &si->Node;
            SmokeableInfoList.prev = &si->Node;
            si->Node.prev = tail;
            si->Node.next = &SmokeableInfoList;
            smokeableinfo_memory_image_load(si);
        }
        for (it = SmokeableInfoList.next; it != &SmokeableInfoList;
             it = it->next) {
            SmokeableInfo *si = (SmokeableInfo *)(void *)it;

            for (k = 0; k < 4; k++)
                if (si->ChildNameHashes[k] != 0)
                    si->pChildren[k] =
                        find_smokeable_info(si->ChildNameHashes[k]);
        }
        return 1;
    }
    if (type == 0x00034027u) {
        pSmokeableSpawners = (SmokeableSpawner *)(void *)(chunk + 8);
        NumSmokeableSpawners = (int32_t)(bchunk_u32(chunk + 4) >> 3);
        return 1;
    }
    return 0;
}

int smokeable_unloader(uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);

    if (type == 0x00034026u) {
        int32_t  n, i;
        uint8_t *data = chunk_records(chunk, &n);

        for (i = 0; i < n; i++) {
            bNode *node = (bNode *)(void *)(data + i * sizeof(SmokeableInfo));
            bNode *next = node->next, *prev = node->prev;

            prev->next = next;
            next->prev = prev;
        }
        return 1;
    }
    if (type == 0x00034027u) {
        pSmokeableSpawners = NULL;
        NumSmokeableSpawners = 0;
        return 1;
    }
    return 0;
}

SmokeableInfo *find_smokeable_info(uint32_t hash)
{
    bNode *n;

    for (n = SmokeableInfoList.next; n != &SmokeableInfoList; n = n->next)
        if (((SmokeableInfo *)(void *)n)->NameHash == hash)
            return (SmokeableInfo *)(void *)n;
    return NULL;
}
