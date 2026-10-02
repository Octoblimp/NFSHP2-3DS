// carloader -- retail's CarLoader (0x001b0260 .. 0x001b0fd0): the car
// bodies, dashes and skins the game wants resident, and the loads that
// bring them in.
//
// Load says a ride is wanted. It counts one more instance of the car's
// body, of its dash when the ride has one, and of its skin, making each
// entry it has none for. BeginLoading then starts one load: the textures
// of the skins not yet loaded, one skin at a time when RoundRobinFlag is
// set and all of them when it is not, or, once every skin is loaded or
// loading, the first body or dash not yet loaded. Each load's completion
// is LoadingDoneCallback, which marks what was loading as loaded, drops
// what nobody wants any more and starts the next load. When nothing is
// left to start it calls the callback BeginLoading was given, once.
// Unload counts the instances back down, and what reaches 0 is unloaded
// and freed unless it is still loading.
//
// Retail's Load, IsLoaded and Unload read each car's Compressed names
// (CarTypeInfo+96 and +160) where the demo's read the plain ones (+64 and
// +128), and retail rewrote LoadedSkin::GetUsedTextures: a skin of -1 is
// every skin the car has, through CarTypeInfo's two getters, which are
// new in retail. The rest is the demo's code.
//
// The resource system and TexturePack's file loads are not ported, so the
// five calls into them are seams. Each completion goes through
// carloader_loading_done_callback_bridge with the loader as its
// parameter, as retail's goes through LoadingDoneCallbackBridge; a seam
// must not run it before it returns, because retail's never does --
// ServiceResourceLoading runs the completions, after the frame.
//
// Written up in docs/formats/car-loader.md; cross-checked by
// tools/carloader_check.py against the retail image.

#ifndef CARLOADER_H
#define CARLOADER_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bslotpool.h"
#include "car.h"
#include "texturepack.h"

// LoadedCar, 48 bytes: one geometry file, a body or a dash.
typedef struct LoadedCar {
    bNode    Node;                  //  0
    int8_t   NumInstances;          //  8
    int8_t   Loading;               //  9
    int8_t   Loaded;                // 10
    int8_t   Padding;               // 11
    void    *pResourceFile;         // 12
    char     GeometryFilename[32];  // 16
} LoadedCar;                        // 48

// LoadedSkin, 20 bytes: one car in one skin. HasDash says its textures
// include the dash's.
typedef struct LoadedSkin {
    bNode    Node;                  //  0
    RideInfo TheRideInfo;           //  8
    int8_t   NumInstances;          // 16
    int8_t   Loading;               // 17
    int8_t   Loaded;                // 18
} LoadedSkin;                       // 20

// CarLoader, 32 bytes.
typedef struct CarLoader {
    void   (*pCallback)(void);      //  0
    int32_t  RoundRobinFlag;        //  4
    int32_t  InFrontEndFlag;        //  8
    int32_t  LoadingInProgress;     // 12
    bNode    LoadedCarList;         // 16
    bNode    LoadedSkinList;        // 24
} CarLoader;                        // 32

// The console's layout, which the pool's 48-byte slots rely on. A 64-bit
// host's pointers make every one wider.
#if UINTPTR_MAX == 0xffffffffu
typedef char carloader_layout_check[
    (sizeof(LoadedCar) == 48 && offsetof(LoadedCar, pResourceFile) == 12
     && offsetof(LoadedCar, GeometryFilename) == 16
     && sizeof(LoadedSkin) == 20 && offsetof(LoadedSkin, TheRideInfo) == 8
     && offsetof(LoadedSkin, NumInstances) == 16
     && sizeof(CarLoader) == 32 && offsetof(CarLoader, LoadedCarList) == 16
     && offsetof(CarLoader, LoadedSkinList) == 24) ? 1 : -1];
#endif

// 0x00313a38. Its static constructor (0x001b0d68) is
// carloader_static_init.
extern CarLoader TheCarLoader;

// gp-18888, "LoadedCarSlotPool": 42 slots of 48 bytes, which the cars and
// the skins share.
extern BSlotPool *LoadedCarSlotPool;

// gp-21436, the "CarTextures" pack over CARS\TEXTURES.BIN, which
// LoadGlobalChunks builds (0x001685e8). Nothing in the port builds it
// yet; the loader only hands it to the two texture seams.
extern TexturePack *pCarTexturePack;

// A load's completion, and the parameter it is called with.
typedef void (*CarLoaderDoneFn)(intptr_t param);

// LoadResourceFile (0x00199640): the file, its ResourceFileType (5 for a
// car) and the third argument (8 for a car), the completion and its
// parameter. Its answer is the ResourceFile, kept for the unload.
extern void *(*gCarLoadResourceFileFn)(const char *name, int type, int arg,
                                       CarLoaderDoneFn done, intptr_t param);
// ServiceResourceLoading (0x00199788), which UnloadEverything runs until
// nothing is left loading.
extern void (*gServiceResourceLoadingFn)(void);
// TexturePack::LoadTexturesFromFile (0x001acc98) and
// UnloadTexturesFromFile (0x001acd90), on pCarTexturePack, with n name
// hashes.
extern void (*gLoadTexturesFromFileFn)(TexturePack *p, uint32_t *hashes,
                                       int n, CarLoaderDoneFn done,
                                       intptr_t param);
extern void (*gUnloadTexturesFromFileFn)(TexturePack *p, uint32_t *hashes,
                                         int n);
// The fifth, UnloadResourceFile (0x00199728), is trackflow.h's
// gUnloadResourceFileFn.

// _GLOBAL_$I$TheCarLoader (0x001b0d68): no callback, round robin on, not
// in the front end, nothing loading, both lists empty.
void carloader_static_init(void);

// The same for any loader. Retail's constructor is inline, and only the
// static one runs it.
void carloader_construct(CarLoader *cl);

// ~CarLoader (0x001b0cf8), without the delete: every skin and then every
// car unlinked and freed into the pool, as the two bTList destructors
// (0x001b0da8, 0x001b0e18) free them. Nothing is unloaded first.
// _GLOBAL_$D$TheCarLoader (0x001b0d58) runs it at exit.
void carloader_destruct(CarLoader *cl);

// InitCarLoader (0x001b0260) and CloseCarLoader (0x001b0290): the pool.
void init_car_loader(void);
void close_car_loader(void);

// LoadedSkin(RideInfo *) (0x001b02b8): the ride copied in and the three
// counts 0. The links and byte 19 are left as the pool gave them.
LoadedSkin *loadedskin_construct(LoadedSkin *s, const RideInfo *ri);

// LoadedSkin::GetUsedTextures (0x001b02f8): appends to tex[0..num) the
// textures this skin draws with that are not there already, and answers
// the new count. It stops, with the count so far, at the first one that
// would make it more than max. A skin of -1 is every skin the car has, in
// turn, with SkinNumber set to each while its textures are listed and
// back to -1 after.
int loadedskin_get_used_textures(LoadedSkin *s, uint32_t *tex, int num,
                                 int max, int in_front_end);

// LoadedCar(const char *) (0x001b0470): the name copied in, the counts 0
// and no file.
LoadedCar *loadedcar_construct(LoadedCar *c, const char *name);

// 0x001b04b0 and 0x001b0518: the first entry with that name, or with that
// car and skin; NULL with none.
LoadedCar *carloader_find_loaded_car(CarLoader *cl, const char *name);
LoadedSkin *carloader_find_loaded_skin(CarLoader *cl, int32_t type,
                                       int32_t skin);

// Load (0x001b0560): one more instance of the ride. The answer is the
// body's count before this one, as a signed byte.
int carloader_load(CarLoader *cl, const RideInfo *ri);

// IsLoaded (0x001b06f8). With `requested` set, whether every entry the
// ride needs exists; without, whether each is loaded as well.
int carloader_is_loaded(CarLoader *cl, const RideInfo *ri, int requested);

// Unload (0x001b07e0): one instance fewer, when the ride was loaded at
// all, and then RemoveUnusedCarsAndSkins.
void carloader_unload(CarLoader *cl, const RideInfo *ri);

// UnloadEverything (0x001b08c0): every count to 0, and then
// RemoveUnusedCarsAndSkins and ServiceResourceLoading until both lists are
// empty.
void carloader_unload_everything(CarLoader *cl);

// RemoveUnusedCarsAndSkins (0x001b09b0). An entry with no instances is
// unloaded when it is loaded and freed when it is not loading.
void carloader_remove_unused_cars_and_skins(CarLoader *cl);

// BeginLoading (0x001b0b00). A callback replaces the one kept; NULL keeps
// it. Nothing starts while a load is in progress.
void carloader_begin_loading(CarLoader *cl, void (*callback)(void));

// LoadingDoneCallback (0x001b0c30) and its bridge (0x001b0da0), which is
// what the seams are handed.
void carloader_loading_done_callback(CarLoader *cl);
void carloader_loading_done_callback_bridge(intptr_t param);

#endif
