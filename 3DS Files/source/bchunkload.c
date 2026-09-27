// bchunkload -- see bchunkload.h.

#include "bchunkload.h"

#include <stddef.h>

#include "bchunk.h"
#include "difficultyinfo.h"
#include "esolid.h"
#include "polyhedra.h"
#include "scenery.h"
#include "track.h"
#include "trackpath.h"
#include "trackroute.h"

int32_t bchunk_breaks;

void (*gUnportedLoaderFn)(int slot, int unload, uint8_t *chunk);
void (*gELightUpdateTexturesFn)(void);
void (*gAfxUpdateTexturesFn)(void);
void (*gFlailerPostLoadFixupFn)(void);
void (*gEmptyFernFlattenersFn)(void);

static void bbreak(void)
{
    bchunk_breaks++;
}

static uint8_t *next_chunk(uint8_t *c)
{
    return c + 8 + bchunk_u32(c + 4);
}

int loader_null(uint8_t *chunk)
{
    return bchunk_u32(chunk) == 0;
}

// ------------------------------------------------------ the ported slots

static int LoaderTrackGeometry(uint8_t *c)
{
    return track_loader_geometry(c);
}

static int UnloaderTrackGeometry(uint8_t *c)
{
    return track_unloader_geometry(c);
}

static int LoaderScenery(uint8_t *c)
{
    return (int)scenery_loader(c);
}

static int UnloaderScenery(uint8_t *c)
{
    return (int)scenery_unloader(c);
}

static int LoaderTrackRoutes(uint8_t *c)
{
    return track_routes_loader(c);
}

static int UnloaderTrackRoutes(uint8_t *c)
{
    return track_routes_unloader(c);
}

static int UnloaderTrackPath(uint8_t *c)
{
    return unloader_track_path(c);
}

static int UnloaderDifficultyInfo(uint8_t *c)
{
    return unloader_difficulty_info(c);
}

// ---------------------------------------------------- the unported slots

// A slot whose object is not ported: the image's guard, and the chunk to
// the seam.
static int take(const uint32_t *types, size_t n, int slot, int unload,
                uint8_t *c)
{
    uint32_t type = bchunk_u32(c);
    size_t i;

    for (i = 0; i < n; i++) {
        if (types[i] == type) {
            if (gUnportedLoaderFn != NULL)
                gUnportedLoaderFn(slot, unload, c);
            return 1;
        }
    }
    return 0;
}

#define UNPORTED(load, unload, slot, ...)                                 \
    static const uint32_t load##Types[] = { __VA_ARGS__ };                \
    static int load(uint8_t *c)                                           \
    {                                                                     \
        return take(load##Types, sizeof load##Types / sizeof(uint32_t),   \
                    slot, 0, c);                                          \
    }                                                                     \
    static int unload(uint8_t *c)                                         \
    {                                                                     \
        return take(load##Types, sizeof load##Types / sizeof(uint32_t),   \
                    slot, 1, c);                                          \
    }

UNPORTED(LoaderTexturePack, UnloaderTexturePack, 2,
         0xb0300001u, 0xb0300100u)
UNPORTED(LoaderFontInfo, UnloaderFontInfo, 3, 0x00015010u, 0x00030200u)
UNPORTED(LoaderLightList, UnloaderLightList, 5,
         0x80034015u, 0x80034019u, 0x0003401cu, 0x0003401eu)
UNPORTED(LoaderAcidFX, UnloaderAcidFX, 6,
         0x80035000u, 0x80035010u, 0x00035020u, 0x00035021u)
UNPORTED(LoaderEventManager, UnloaderEventManager, 7, 0x80036000u)
UNPORTED(LoaderPositionMarkers, UnloaderPositionMarkers, 8, 0x00034013u)
UNPORTED(LoaderFlailerChunk, UnloaderFlailerChunk, 10, 0x80010200u)
UNPORTED(LoaderAnimations, UnloaderAnimations, 12, 0x80034008u)
UNPORTED(LoaderCameras, UnloaderCameras, 13,
         0x80034405u, 0x80034410u, 0x80034415u, 0x80034420u, 0x80034425u,
         0x00034492u)
UNPORTED(LoaderSun, UnloaderSun, 14, 0x00034202u)
UNPORTED(LoaderCops, UnloaderCops, 15, 0x80034500u)
UNPORTED(LoaderCarInfo, UnloaderCarInfo, 16, 0x00034600u, 0x00034601u)
UNPORTED(LoaderBodyDamage, UnloaderBodyDamage, 17, 0x00034030u)
UNPORTED(LoaderPhysPredict, UnloaderPhysPredict, 20, 0x00034700u)
UNPORTED(LoaderNisInfo, UnloaderNisInfo, 21, 0x00037010u)
UNPORTED(LoaderSoundScape, UnloaderSoundScape, 22, 0x80038000u)
UNPORTED(LoaderCharacterInfo, UnloaderCharacterInfo, 23,
         0x00034300u, 0x00034301u)
UNPORTED(LoaderHeliSheet, UnloaderHeliSheet, 24, 0x00034800u)
UNPORTED(LoaderEventTree, UnloaderEventTree, 25, 0x80034a00u)
UNPORTED(LoaderLanguage, UnloaderLanguage, 27, 0x00039000u)
UNPORTED(LoaderSmokeables, UnloaderSmokeables, 28, 0x00034026u, 0x00034027u)
UNPORTED(LoaderWeatherMan, UnloaderWeatherMan, 29, 0x00034250u)
UNPORTED(LoaderDemoModeReplay, UnloaderDemoModeReplay, 30,
         0x00039100u, 0x00039101u, 0x00039102u)

// --------------------------------------------------------------- tables

BChunkLoader LoaderTable[BCHUNK_NUM_LOADERS] = {
    loader_null,                    //  0
    LoaderTrackGeometry,            //  1
    LoaderTexturePack,              //  2
    LoaderFontInfo,                 //  3
    loader_solid_list,              //  4
    LoaderLightList,                //  5
    LoaderAcidFX,                   //  6
    LoaderEventManager,             //  7
    LoaderPositionMarkers,          //  8
    loader_collision_volumes,       //  9
    LoaderFlailerChunk,             // 10
    LoaderScenery,                  // 11
    LoaderAnimations,               // 12
    LoaderCameras,                  // 13
    LoaderSun,                      // 14
    LoaderCops,                     // 15
    LoaderCarInfo,                  // 16
    LoaderBodyDamage,               // 17
    LoaderTrackRoutes,              // 18
    loader_track_path,              // 19
    LoaderPhysPredict,              // 20
    LoaderNisInfo,                  // 21
    LoaderSoundScape,               // 22
    LoaderCharacterInfo,            // 23
    LoaderHeliSheet,                // 24
    LoaderEventTree,                // 25
    loader_difficulty_info,         // 26
    LoaderLanguage,                 // 27
    LoaderSmokeables,               // 28
    LoaderWeatherMan,               // 29
    LoaderDemoModeReplay,           // 30
};

BChunkLoader UnloaderTable[BCHUNK_NUM_LOADERS] = {
    loader_null,                    //  0
    UnloaderTrackGeometry,          //  1
    UnloaderTexturePack,            //  2
    UnloaderFontInfo,               //  3
    unloader_solid_list,            //  4
    UnloaderLightList,              //  5
    UnloaderAcidFX,                 //  6
    UnloaderEventManager,           //  7
    UnloaderPositionMarkers,        //  8
    unloader_collision_volumes,     //  9
    UnloaderFlailerChunk,           // 10
    UnloaderScenery,                // 11
    UnloaderAnimations,             // 12
    UnloaderCameras,                // 13
    UnloaderSun,                    // 14
    UnloaderCops,                   // 15
    UnloaderCarInfo,                // 16
    UnloaderBodyDamage,             // 17
    UnloaderTrackRoutes,            // 18
    UnloaderTrackPath,              // 19
    UnloaderPhysPredict,            // 20
    UnloaderNisInfo,                // 21
    UnloaderSoundScape,             // 22
    UnloaderCharacterInfo,          // 23
    UnloaderHeliSheet,              // 24
    UnloaderEventTree,              // 25
    UnloaderDifficultyInfo,         // 26
    UnloaderLanguage,               // 27
    UnloaderSmokeables,             // 28
    UnloaderWeatherMan,             // 29
    UnloaderDemoModeReplay,         // 30
};

// ---------------------------------------------------------------- walks

void traverse_chunks(uint8_t *first, uint8_t *end, BChunkLoader *table,
                     int num)
{
    uint8_t *c = first;
    int slot = 0;
    int misses = 0;

    while (c != end) {
        if (table[slot](c)) {
            // The next chunk starts at the slot that took this one.
            c = next_chunk(c);
            misses = 0;
        } else {
            slot++;
            misses++;
            if (slot == num)
                slot = 0;
            // Nobody took it. The count is not reset, so from here each
            // chunk has one try until one is taken.
            if (misses > num) {
                bbreak();
                c = next_chunk(c);
            }
        }
    }
}

void traverse_chunks_backwards(uint8_t *first, uint8_t *end,
                               BChunkLoader *table, int num)
{
    while (first != end) {
        uint8_t *c = first;
        uint8_t *n = next_chunk(c);
        int slot;

        // The last chunk before `end`, found from the start each time.
        while (n != end) {
            c = n;
            n = next_chunk(c);
        }
        end = c;
        for (slot = 0; slot < num; slot++) {
            if (table[slot](c))
                break;
        }
        if (slot == num)
            bbreak();
    }
}

void load_chunks(uint8_t *chunks, int32_t size)
{
    if (chunks == NULL || size == 0)
        return;
    traverse_chunks(chunks, chunks + size, LoaderTable, BCHUNK_NUM_LOADERS);
}

void unload_chunks(uint8_t *chunks, int32_t size)
{
    if (chunks == NULL || size == 0)
        return;
    traverse_chunks_backwards(chunks, chunks + size, UnloaderTable,
                              BCHUNK_NUM_LOADERS);
}

void post_load_fixup(void)
{
    efix_up_tables();
    if (gELightUpdateTexturesFn != NULL)
        gELightUpdateTexturesFn();
    if (gAfxUpdateTexturesFn != NULL)
        gAfxUpdateTexturesFn();
    if (gFlailerPostLoadFixupFn != NULL)
        gFlailerPostLoadFixupFn();
}

void hot_chunks_post_load_fixup(void)
{
    post_load_fixup();
    if (gEmptyFernFlattenersFn != NULL)
        gEmptyFernFlattenersFn();
}
