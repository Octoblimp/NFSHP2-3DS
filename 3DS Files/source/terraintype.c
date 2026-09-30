// terraintype -- retail's TerrainType.obj's code, which is the demo's but for
// the table's stride and address. The table is terraintypetab.c.

#include "terraintype.h"

#include <stddef.h>

#include "bchunk.h"

// bToUpper, 0x00253790 (the demo's 0x0023b568): the char sign-extended,
// and only a-z folded -- by clearing bit 5, which is all the ASCII fold
// needs.
static int32_t to_upper(char c)
{
    int32_t v = (int8_t)c;

    if ((uint32_t)(v - 97) < 26u)
        v &= 0x5f;
    return v;
}

// bStrICmp, 0x002536a8 (the demo's 0x0023b480). Both characters are
// fetched and folded before either is tested, and the difference is of the
// folded, sign-extended values.
static int32_t str_icmp(const char *a, const char *b)
{
    for (;;) {
        int32_t ca = to_upper(*a++);
        int32_t cb = to_upper(*b++);

        if (ca == 0 || cb == 0 || ca != cb)
            return ca - cb;
    }
}

// 0x001d4428 (the demo's 0x001ca078).
int32_t terrain_match_name(const char *name)
{
    int32_t i;

    if (name == NULL)
        return TERRAIN_TYPE_NONE;
    for (i = 0; i < NUM_TERRAIN_TYPES; i++) {
        if (str_icmp(name, TerrainTypeInfoTable[i].Name) == 0)
            return i;
    }
    return TERRAIN_TYPE_NONE;
}

// 0x001d4498 (the demo's 0x001ca0e8).
int32_t terrain_match_hash(uint32_t hash)
{
    int32_t i;

    for (i = 0; i < NUM_TERRAIN_TYPES; i++) {
        if (TerrainTypeInfoTable[i].NameHash == hash)
            return i;
    }
    return TERRAIN_TYPE_NONE;
}

// 0x001d44d0 (the demo's 0x001ca120).
void terraintype_static_init(void)
{
    int32_t i;

    for (i = 0; i < NUM_TERRAIN_TYPES; i++)
        TerrainTypeInfoTable[i].NameHash =
            bchunk_hash(TerrainTypeInfoTable[i].Name);
}
