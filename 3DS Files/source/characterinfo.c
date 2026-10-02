// characterinfo -- see characterinfo.h.

#include "characterinfo.h"

#include "bchunk.h"

BodyTypeInfo  *pBodyTypeInfo;                   // gp-17700
int32_t        NumBodyTypeInfo;                 // gp-17696
CharacterInfo *pCharacterInfo;                  // gp-17692
int32_t        NumCharacterInfo;                // gp-17688

// bStrICmp, 0x002536a8, as terraintype.c has it: both characters folded,
// sign-extended, before either is tested.
static int32_t to_upper(char c)
{
    int32_t v = (int8_t)c;

    if ((uint32_t)(v - 97) < 26u)
        v &= 0x5f;
    return v;
}

static int32_t str_icmp(const char *a, const char *b)
{
    for (;;) {
        int32_t ca = to_upper(*a++);
        int32_t cb = to_upper(*b++);

        if (ca == 0 || cb == 0 || ca != cb)
            return ca - cb;
    }
}

int loader_character_info(uint8_t *chunk)
{
    uint32_t id = bchunk_u32(chunk);
    uint32_t size = bchunk_u32(chunk + 4);

    if (id == BODY_TYPE_INFO_CHUNK) {
        pBodyTypeInfo = (BodyTypeInfo *)(void *)(chunk + 8);
        NumBodyTypeInfo = (int32_t)(size / 180u);
        return 1;
    }
    if (id == CHARACTER_INFO_CHUNK) {
        pCharacterInfo = (CharacterInfo *)(void *)(chunk + 8);
        NumCharacterInfo = (int32_t)(size / 68u);
        return 1;
    }
    return 0;
}

int unloader_character_info(uint8_t *chunk)
{
    uint32_t id = bchunk_u32(chunk);

    if (id == BODY_TYPE_INFO_CHUNK) {
        pBodyTypeInfo = NULL;
        NumBodyTypeInfo = 0;
        return 1;
    }
    if (id == CHARACTER_INFO_CHUNK) {
        pCharacterInfo = NULL;
        NumCharacterInfo = 0;
        return 1;
    }
    return 0;
}

BodyTypeInfo *get_body_type_info(const char *name)
{
    int32_t i;

    for (i = 0; i < NumBodyTypeInfo; i++) {
        if (str_icmp(name, pBodyTypeInfo[i].BodyTypeName) == 0)
            return &pBodyTypeInfo[i];
    }
    return NULL;
}

CharacterInfo *get_character_info_by_name(const char *name)
{
    int32_t i;

    for (i = 0; i < NumCharacterInfo; i++) {
        if (str_icmp(name, pCharacterInfo[i].CharacterName) == 0)
            return &pCharacterInfo[i];
    }
    return NULL;
}

CharacterInfo *get_character_info_from_name_hash(uint32_t hash)
{
    int32_t i;

    for (i = 0; i < NumCharacterInfo; i++) {
        if (bchunk_hash(pCharacterInfo[i].CharacterName) == hash)
            return &pCharacterInfo[i];
    }
    return NULL;
}

int32_t get_num_character_infos(void)
{
    return NumCharacterInfo;
}

CharacterInfo *get_character_info(int32_t i)
{
    if (i < 0 || i >= NumCharacterInfo)
        return NULL;
    return &pCharacterInfo[i];
}
