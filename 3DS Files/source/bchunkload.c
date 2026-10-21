// bchunkload -- see bchunkload.h.

#include "bchunkload.h"

#include <stddef.h>

#include "acidsys.h"
#include "bchunk.h"
#include "cameracoord.h"
#include "cardamage.h"
#include "carinfo.h"
#include "characterinfo.h"
#include "copmgr.h"
#include "difficultyinfo.h"
#include "eanim.h"
#include "elight.h"
#include "epositionmarker.h"
#include "esolid.h"
#include "eventmgr.h"
#include "eventtree.h"
#include "helisheet.h"
#include "nisinfo.h"
#include "polyhedra.h"
#include "scenery.h"
#include "smokeable.h"
#include "soundscape.h"
#include "sun.h"
#include "texturepack.h"
#include "track.h"
#include "trackpath.h"
#include "trackroute.h"
#include "weatherman.h"

int32_t bchunk_breaks;

void (*gUnportedLoaderFn)(int slot, int unload, uint8_t *chunk);
BChunkLoader gDemoModeReplayLoaderFn;
BChunkLoader gDemoModeReplayUnloaderFn;
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

static int LoaderCarInfo(uint8_t *c)
{
    return loader_car_info(c);
}

static int UnloaderCarInfo(uint8_t *c)
{
    return unloader_car_info(c);
}

static int LoaderCharacterInfo(uint8_t *c)
{
    return loader_character_info(c);
}

static int UnloaderCharacterInfo(uint8_t *c)
{
    return unloader_character_info(c);
}

static int LoaderSmokeables(uint8_t *c)
{
    return smokeable_loader(c);
}

static int UnloaderSmokeables(uint8_t *c)
{
    return smokeable_unloader(c);
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

UNPORTED(LoaderFontInfo, UnloaderFontInfo, 3, 0x00015010u, 0x00030200u)
UNPORTED(LoaderFlailerChunk, UnloaderFlailerChunk, 10, 0x80010200u)
UNPORTED(LoaderLanguage, UnloaderLanguage, 26, 0x00039000u)
UNPORTED(LoaderDemoModeReplayGuard, UnloaderDemoModeReplayGuard, 29,
         0x00039100u, 0x00039101u, 0x00039102u)

// Slot 29, TheDemoModeReplay's (dmreplay.c), through its seams; the guard
// alone without them.
static int LoaderDemoModeReplay(uint8_t *c)
{
    if (gDemoModeReplayLoaderFn != NULL)
        return gDemoModeReplayLoaderFn(c);
    return LoaderDemoModeReplayGuard(c);
}

static int UnloaderDemoModeReplay(uint8_t *c)
{
    if (gDemoModeReplayUnloaderFn != NULL)
        return gDemoModeReplayUnloaderFn(c);
    return UnloaderDemoModeReplayGuard(c);
}

// --------------------------------------------------------------- tables

// Retail's order, which is the demo's without PhysPredict, the demo's slot
// 20: retail has no 0x34700 chunk and no loader for one.
BChunkLoader LoaderTable[BCHUNK_NUM_LOADERS] = {
    loader_null,                    //  0
    LoaderTrackGeometry,            //  1
    loader_texture_pack,            //  2
    LoaderFontInfo,                 //  3
    loader_solid_list,              //  4
    loader_light_list,              //  5
    loader_acid_fx,                 //  6
    loader_event_manager,           //  7
    loader_position_markers,        //  8
    loader_collision_volumes,       //  9
    LoaderFlailerChunk,             // 10
    LoaderScenery,                  // 11
    eanim_loader,                   // 12
    loader_cameras,                 // 13
    loader_sun,                     // 14
    copmgr_loader,                  // 15
    LoaderCarInfo,                  // 16
    loader_body_damage,             // 17
    LoaderTrackRoutes,              // 18
    loader_track_path,              // 19
    loader_nis_info,                // 20
    loader_sound_scape,             // 21
    LoaderCharacterInfo,            // 22
    loader_heli_sheet,              // 23
    loader_event_tree,              // 24
    loader_difficulty_info,         // 25
    LoaderLanguage,                 // 26
    LoaderSmokeables,               // 27
    loader_weather_man,             // 28
    LoaderDemoModeReplay,           // 29
};

BChunkLoader UnloaderTable[BCHUNK_NUM_LOADERS] = {
    loader_null,                    //  0
    UnloaderTrackGeometry,          //  1
    unloader_texture_pack,          //  2
    UnloaderFontInfo,               //  3
    unloader_solid_list,            //  4
    unloader_light_list,            //  5
    unloader_acid_fx,               //  6
    unloader_event_manager,         //  7
    unloader_position_markers,      //  8
    unloader_collision_volumes,     //  9
    UnloaderFlailerChunk,           // 10
    UnloaderScenery,                // 11
    eanim_unloader,                 // 12
    unloader_cameras,               // 13
    unloader_sun,                   // 14
    copmgr_unloader,                // 15
    UnloaderCarInfo,                // 16
    unloader_body_damage,           // 17
    UnloaderTrackRoutes,            // 18
    UnloaderTrackPath,              // 19
    unloader_nis_info,              // 20
    unloader_sound_scape,           // 21
    UnloaderCharacterInfo,          // 22
    unloader_heli_sheet,            // 23
    unloader_event_tree,            // 24
    UnloaderDifficultyInfo,         // 25
    UnloaderLanguage,               // 26
    UnloaderSmokeables,             // 27
    unloader_weather_man,           // 28
    UnloaderDemoModeReplay,         // 29
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
