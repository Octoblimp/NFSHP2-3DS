// weatherman -- WeatherMan.obj (0x0019dfe8 .. 0x0019ec18): the track's
// weather regions, slot 29 of the LoaderTable, and the query that blends
// them for a point. With it, eView::GetWeatherQuery (0x001123f8) and its
// cache, which EcstasyE.obj keeps beside eDisplayFrame.
//
// A track has one 0x34250 chunk: a WeatherRegionPack at the next 16 in the
// chunk, then NumRegions WeatherRegions of 128 bytes each. The loader links
// each region onto its type's list, in the order the pack has them. Rain,
// fog, snow and wind each have a list. A type past 3 goes on none. The
// regions stay in the chunk, and the lists are threaded through their
// first eight bytes.
//
// A region is a sphere. Radius is where it ends. FarFalloffStart is where
// it starts to fade, and a region whose two radii are equal does not fade.
// WeatherManQuery takes each list in turn:
//   - Of the regions with no fade that hold the point, the nearest is the
//     root.
//   - Up to three that fade are hits. Each scales by 1 - (d^2 - f^2) /
//     (r^2 - f^2) for a distance d, a radius r and a fade start f.
//   - The hits' scales are summed. What is left of 1 is the root's, and
//     past a sum of 1 the hits share it and the root gets none.
// For fog, the colour, the start and the amount are blended by those
// weights. For rain, snow and wind only the intensity is. The listing
// weights each hit's intensity by HitScale alone, not by its own scale as
// well, as the fog's is weighted.
//
// TRACKB12's chunk is version 2 with twenty fog regions:
//   - FOG<MAIN>, 2005 wide with no fade, at 0.1 of 0xa0a082 from 246;
//   - eleven FOG<TUNNEL>s, 85 wide fading from 55, at 0;
//   - six FOG<SMOKE>s, 50 fading from 25, at 0.8 of 0x6e6e6e;
//   - three FOG<TUNNELSM>s, 46.42 fading from 29.32, at 0.
// So in a tunnel the fog thins, and in the smoke it thickens and greys.
//
// The one change: WeatherAddRegion leaves a region of a type past 3 linked
// to itself. The image leaves it holding the chunk's bytes, and the
// unloader then writes through them. With the self-link it unlinks from
// nothing.
//
// Not here: the static destructor, which runs at exit and hands each
// region to operator delete; SoundScape::UpdateWeather and UpdateStorm,
// the query's other callers, which are the sound's and the storm's.
// Neither is called in the image (rain.h), so CreateFogPalette is the
// query's one live reader.
//
// Cross-check: tools/weather_check.py. Write-up: docs/formats/weather-fog.md.

#ifndef WEATHERMAN_H
#define WEATHERMAN_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bvector.h"
#include "eview.h"

// WeatherType (.mdebug type#3891): which list a region goes on.
enum {
    WEATHER_RAIN = 0,
    WEATHER_FOG  = 1,
    WEATHER_SNOW = 2,
    WEATHER_WIND = 3,
    WEATHER_NUM_TYPES = 4
};

// WeatherRegion, 128 bytes (type#3901).
typedef struct WeatherRegion {
    bNode     Node;                         //   0  bTNode<WeatherRegion>
    uint32_t  NameHash;                     //   8
    uint32_t  GroupNameHash;                //  12
    char      Name[32];                     //  16
    char      GroupName[32];                //  48
    int32_t   Type;                         //  80  WeatherType
    uint32_t  FogColour;                    //  84  r, g, b, a from the bottom
    float     FogStart;                     //  88  a palette index
    float     Parameter1;                   //  92
    float     PositionX;                    //  96
    float     PositionY;                    // 100
    float     PositionZ;                    // 104
    float     Radius;                       // 108
    float     Intensity;                    // 112
    float     FarFalloffStart;              // 116
    uint32_t  pad0;                         // 120
    uint32_t  pad1;                         // 124
} WeatherRegion;

// WeatherRegionPack, 16 bytes (type#3926). The .mdebug does not name its
// first eight bytes, and nothing reads them.
typedef struct WeatherRegionPack {
    uint32_t  Unnamed[2];                   //   0
    int32_t   Version;                      //   8  2
    int32_t   NumRegions;                   //  12
} WeatherRegionPack;                        //  16, then the regions

// WeatherQuery, 96 bytes (type#3227): what a point gets.
typedef struct WeatherQuery {
    float        Rain;                      //  0
    float        Fog;                       //  4  the amount, 0 to 1
    float        Snow;                      //  8
    float        Wind;                      // 12
    uint32_t     FogColour;                 // 16
    float        FogStart;                  // 20  a palette index
    float        RootScale;                 // 24
    float        HitScale;                  // 28
    const char  *RegionR;                   // 32  the root's Name
    uint32_t     RegionR_Colour;            // 36
    float        RegionR_FogStart;          // 40
    float        RegionR_Scale;             // 44
    const char  *Region0;                   // 48  the hits'
    uint32_t     Region0_Colour;            // 52
    float        Region0_FogStart;          // 56
    float        Region0_Scale;             // 60
    const char  *Region1;                   // 64
    uint32_t     Region1_Colour;            // 68
    float        Region1_FogStart;          // 72
    float        Region1_Scale;             // 76
    const char  *Region2;                   // 80
    uint32_t     Region2_Colour;            // 84
    float        Region2_FogStart;          // 88
    float        Region2_Scale;             // 92
} WeatherQuery;

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char weatherman_layout_check[
    (sizeof(WeatherRegion) == 128 && offsetof(WeatherRegion, Type) == 80
     && offsetof(WeatherRegion, FarFalloffStart) == 116
     && sizeof(WeatherRegionPack) == 16 && sizeof(WeatherQuery) == 96
     && offsetof(WeatherQuery, Region2_Scale) == 92) ? 1 : -1];
#endif

#define WEATHER_CHUNK_ID      0x00034250u
#define WEATHER_PACK_VERSION  2

// WeatherRegionLists, 0x00308fe0: by WeatherType. WeatherRegionInactiveList,
// 0x00323df8, is where WeatherSetRegionState puts a region it turns off.
// The static constructor (0x0019ebd8) links each to itself, which is where
// these start.
extern bNode WeatherRegionLists[WEATHER_NUM_TYPES];
extern bNode WeatherRegionInactiveList;

// WeatherRainList .. WeatherWindList, 0x00323e00 .. 0x00323e0c: each list
// by name. Nothing in the image reads them.
extern bNode *WeatherRainList;
extern bNode *WeatherFogList;
extern bNode *WeatherSnowList;
extern bNode *WeatherWindList;

// The tweaker's, 0x00323e10 .. 0x00323e24, all 0 in the image. With
// WeatherUseTweakerValues set, the query gives these for the fog, and 0 for
// the rest.
extern int32_t WeatherUseTweakerValues;
extern float   WeatherFog;
extern float   WeatherFogStart;
extern int32_t WeatherFogColourR;
extern int32_t WeatherFogColourG;
extern int32_t WeatherFogColourB;

// WeatherManInit (0x0019dfe8) and WeatherManClose (0x0019dff0) do nothing.
void WeatherManInit(void);
void WeatherManClose(void);

// LoaderWeatherMan(bChunk *), 0x0019dff8, and UnloaderWeatherMan,
// 0x0019e078. They return 0 for a chunk of any other type, and 1 for a
// chunk of this one. A pack that is not version 2 is taken and nothing is
// linked.
int loader_weather_man(uint8_t *chunk);
int unloader_weather_man(uint8_t *chunk);

// 0x0019e0f8: onto the tail of its type's list.
void WeatherAddRegion(WeatherRegion *r);
// 0x0019e138: off whatever list it is on.
void WeatherRemoveRegion(WeatherRegion *r);
// 0x0019e150: off its list, then onto the tail of its type's list if state
// is nonzero, else the inactive list's. The type is not checked. Only
// WeatherSetGroupState calls it, on regions that are on a list, and those
// are all of types 0 to 3.
void WeatherSetRegionState(WeatherRegion *r, int32_t state);
// 0x0019e198: each region in the group, or every region for a hash of 0.
// A state of 0 takes them off the four lists, and any other puts the
// inactive ones back. Nothing in the image calls it.
void WeatherSetGroupState(uint32_t group_hash, int32_t state);

// 0x0019e290.
void WeatherManQuery(WeatherQuery *q, const bVector3 *pos);

// CachedWeatherQueries, 0x002d47b8: one per view, by the view's ID.
extern WeatherQuery CachedWeatherQueries[EVIEW_NUM_VIEWS];

// eView::GetWeatherQuery, 0x001123f8: the view's cached query, queried
// again from the camera's position when the view's WeatherQueryCounter is
// not eFrameCounter. The ID is not checked.
WeatherQuery *eview_get_weather_query(eView *view);

// WeatherTest, 0x00112460, which eDisplayFrame calls: it does nothing.
void WeatherTest(void);

#endif
