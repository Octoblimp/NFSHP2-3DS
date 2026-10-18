// bchunkload -- the loading half of the object at 0x0018f6c8 ..
// 0x0018f918, whose other half is ResourceFile: the walk that hands each
// chunk at a file's top level to the loader that takes it, the walk back
// that hands them to the unloaders, and the two tables of 30 loaders
// they walk: retail's, which dropped the demo's PhysPredict. Retail's
// ResourceFile is at 0x001990d0 .. 0x00199320, and differs from the
// demo's only in LoadChunks' and UnloadChunks' table and count.
//
// A loader looks at a chunk's type and returns 0 for one it does not
// take. TraverseChunks tries the table from the slot that took the last
// chunk; a chunk nobody takes is a bBreak, and so is every chunk after it
// that the slot the walk is on does not take at the first try, until one
// is taken. TraverseChunksBackwards starts from the last chunk and tries
// each from slot 0. On the disc every type has exactly one taker, in both
// tables, and every loader returns nonzero for every chunk of its types.
//
// The slots whose object is ported call it: TrackGeometry (with the
// topology tree), TexturePack, SolidList, CollisionVolumes, Scenery, Sun,
// TrackRoutes, TrackPath and DifficultyInfo. Every other slot is its guard alone: it
// takes the types the image's takes and hands the chunk to
// gUnportedLoaderFn. docs/formats/loader-table.md has the table.

#ifndef BCHUNKLOAD_H
#define BCHUNKLOAD_H

#include <stdint.h>

typedef int (*BChunkLoader)(uint8_t *chunk);

#define BCHUNK_NUM_LOADERS 30

// 0x003081d0 and 0x00308250, the demo's 31 slots; retail's are at
// 0x00310280 and 0x003102f8.
extern BChunkLoader LoaderTable[BCHUNK_NUM_LOADERS];
extern BChunkLoader UnloaderTable[BCHUNK_NUM_LOADERS];

// How many times the walks have reached bBreak (0x00238888), the break
// the debugger stops on. The console carries on past it.
extern int32_t bchunk_breaks;

// A chunk an unported slot takes. `unload` is 1 from UnloaderTable. NULL
// takes it and does nothing.
extern void (*gUnportedLoaderFn)(int slot, int unload, uint8_t *chunk);

// Slot 29's LoaderDemoModeReplay and UnloaderDemoModeReplay (0x0013ef70
// and 0x0013ef98) on TheDemoModeReplay, dmreplay.c's, which main.c binds.
// NULL leaves the slot unported, to gUnportedLoaderFn.
extern BChunkLoader gDemoModeReplayLoaderFn;
extern BChunkLoader gDemoModeReplayUnloaderFn;

// PostLoadFixup's and HotChunksPostLoadFixup's callees that are not
// ported. NULL does nothing.
extern void (*gELightUpdateTexturesFn)(void);
extern void (*gAfxUpdateTexturesFn)(void);
extern void (*gFlailerPostLoadFixupFn)(void);
extern void (*gEmptyFernFlattenersFn)(void);

// LoaderNull(bChunk *), 0x0018f6c8: slot 0 of both tables, which takes
// the padding, type 0.
int loader_null(uint8_t *chunk);

// TraverseChunks(bChunk *, bChunk *, int (**)(bChunk *), int),
// 0x0018f6d8, and TraverseChunksBackwards, 0x0018f790.
void traverse_chunks(uint8_t *first, uint8_t *end, BChunkLoader *table,
                     int num);
void traverse_chunks_backwards(uint8_t *first, uint8_t *end,
                               BChunkLoader *table, int num);

// LoadChunks(bChunk *, int), 0x0018f878, and UnloadChunks, 0x0018f8a0:
// a file's `size` bytes through LoaderTable, or back through
// UnloaderTable. Nothing for a NULL file or a size of 0.
void load_chunks(uint8_t *chunks, int32_t size);
void unload_chunks(uint8_t *chunks, int32_t size);

// PostLoadFixup, 0x0018f8c8: eFixUpTables, then the lights', the effects'
// and the front end's textures. ResourceFile calls it after each load and
// each unload. HotChunksPostLoadFixup, 0x0018f8f8, is that and then
// EmptyFernFlatteners.
void post_load_fixup(void);
void hot_chunks_post_load_fixup(void);

#endif
