// difficultyinfo -- see difficultyinfo.h.

#include "difficultyinfo.h"

#include <string.h>

DifficultyInfo TheDifficultyInfo;

// The id is read as a word, the way bChunk's first member is; the payload
// starts past the eight-byte header.
static uint32_t chunk_id(const uint8_t *chunk)
{
    uint32_t id;

    memcpy(&id, chunk, 4);
    return id;
}

int loader_difficulty_info(uint8_t *chunk)
{
    if (chunk_id(chunk) != DIFFICULTYINFO_CHUNK)
        return 0;
    memcpy(&TheDifficultyInfo, chunk + 8, sizeof TheDifficultyInfo);
    return 1;
}

int unloader_difficulty_info(const uint8_t *chunk)
{
    return chunk_id(chunk) == DIFFICULTYINFO_CHUNK;
}
