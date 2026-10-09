// nisinfo -- the NIS table and its lookups. See nisinfo.h.

#include "nisinfo.h"

#include <stddef.h>

#include "bchunk.h"

NisInfo *NisInfoTable;
int32_t  NumNisInfos;

int loader_nis_info(uint8_t *chunk)
{
    if (bchunk_u32(chunk) != NIS_INFO_CHUNK_ID)
        return 0;
    NisInfoTable = (NisInfo *)(void *)(chunk + 8);
    NumNisInfos = (int32_t)(bchunk_u32(chunk + 4) / 160u);
    return 1;
}

int unloader_nis_info(uint8_t *chunk)
{
    if (bchunk_u32(chunk) != NIS_INFO_CHUNK_ID)
        return 0;
    NisInfoTable = NULL;
    NumNisInfos = 0;
    return 1;
}

int32_t get_num_nis_info(int32_t type)
{
    int32_t i, n = 0;

    if (NisInfoTable == NULL)
        return 0;
    for (i = 0; i < NumNisInfos; i++)
        if (NisInfoTable[i].Type == type)
            n++;
    return n;
}

NisInfo *get_nis_info(int32_t n)
{
    if (NisInfoTable == NULL || n >= NumNisInfos)
        return NULL;
    return &NisInfoTable[n];
}

NisInfo *get_nis_info_by_type(int32_t n, int32_t type)
{
    int32_t i;

    if (NisInfoTable == NULL)
        return NULL;
    for (i = 0; i < NumNisInfos; i++) {
        if (NisInfoTable[i].Type != type)
            continue;
        if (n == 0)
            return &NisInfoTable[i];
        n--;
    }
    return NULL;
}
