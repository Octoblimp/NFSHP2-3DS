// terraintype -- TerrainType.obj (0x001ca078 .. 0x001ca178) and its table.
//
// Every track polygon carries a terrain number (topology.h's
// TopologyTreePolygon.Type), and every consumer of that number -- Wheel's
// friction, Track's road noise, the particle and sound systems -- reads it
// back through TerrainTypeInfoTable, one 140-byte record per terrain. The
// table is data (0x00310a90, 33 entries) and terraintypetab.c carries it
// verbatim, written by tools/gen_terrain_table.py; the object's code is two
// lookups and the static initialiser that hashes the names.
//
// Written up in docs/formats/topology.md.

#ifndef TERRAINTYPE_H
#define TERRAINTYPE_H

#include <stddef.h>
#include <stdint.h>

// The .mdebug's TerrainType (type#2035). A 32-bit enum wherever it is
// stored.
enum {
    TERRAIN_TYPE_NONE = 0,
    TERRAIN_TYPE_ROAD = 1,
    TERRAIN_TYPE_DIRT = 2,
    TERRAIN_TYPE_DIRTROAD = 3,
    TERRAIN_TYPE_PUDDLE = 4,
    TERRAIN_TYPE_DEEP_WATER = 5,
    TERRAIN_TYPE_GRASS = 6,
    TERRAIN_TYPE_SAND = 7,
    TERRAIN_TYPE_SNOW = 8,
    TERRAIN_TYPE_DIRT_SHOULDER = 9,
    TERRAIN_TYPE_SAND_SHOULDER = 10,
    TERRAIN_TYPE_SNOW_SHOULDER = 11,
    TERRAIN_TYPE_SIDEWALK = 12,
    TERRAIN_TYPE_SNOW_SIDEWALK = 13,
    TERRAIN_TYPE_ROCK = 14,
    TERRAIN_TYPE_WOOD_WALL = 15,
    TERRAIN_TYPE_CACTUS_WALL = 16,
    TERRAIN_TYPE_SOLID_WALL = 17,
    TERRAIN_TYPE_BOARDWALK = 18,
    TERRAIN_TYPE_COBBLESTONE = 19,
    TERRAIN_TYPE_MUD_PUDDLE = 20,
    TERRAIN_TYPE_ROUGH_ROAD = 21,
    TERRAIN_TYPE_GRASS_SHOULDER = 22,
    TERRAIN_TYPE_AUTUMN_LEAVES = 23,
    TERRAIN_TYPE_AUTUMN_LEAVES_SHOULDER = 24,
    TERRAIN_TYPE_MULCH = 25,
    TERRAIN_TYPE_MULCH_SHOULDER = 26,
    TERRAIN_TYPE_ROAD_AUTUMN = 27,
    TERRAIN_TYPE_PLANT = 28,
    TERRAIN_TYPE_POST = 29,
    TERRAIN_TYPE_METAL_GRATE = 30,
    TERRAIN_TYPE_POTHOLE = 31,
    TERRAIN_TYPE_CAR = 32,
    NUM_TERRAIN_TYPES = 33
};

// 140 bytes, `.mdebug` type#1584. The seven emitter groups are names --
// `*2`, char pointers, in the stabs, and every one in the table points at
// a string, the empty string where a terrain has none -- that the
// particle system looks up when it needs them.
typedef struct TerrainTypeInfo {
    const char *Name;                        //   0
    uint32_t    NameHash;                    //   4  0 in the ELF; the
                                             //      static init fills it
    int32_t     Type;                        //   8
    uint8_t     ShouldTireMakeRoadSound;     //  12
    uint8_t     ShouldCameraGoThroughIt;     //  13
    uint8_t     _pad0[2];                    //  14
    const char *SkidTextureName;             //  16
    float       RoadNoiseGridSpacingInverse; //  20
    float       RoadNoiseScale;              //  24
    float       StaticFrictionMultiplier;    //  28
    float       DynamicFrictionMultiplier;   //  32
    float       RollingFrictionMultiplier;   //  36
    float       CollisionPriority;           //  40
    float       ForceMagnitude;              //  44
    float       ForceFrequency;              //  48
    uint32_t    DebugTopologyColour;         //  52
    const char *DriveOverEmitterGroup;       //  56
    float       DriveOverMinSpeed;           //  60
    float       DriveOverMaxSpeed;           //  64
    const char *DriveOver2EmitterGroup;      //  68
    float       DriveOver2MinSpeed;          //  72
    float       DriveOver2MaxSpeed;          //  76
    const char *SkidSmokeEmitterGroup;       //  80
    float       SkidSmokeMinSpeed;           //  84
    float       SkidSmokeMaxSpeed;           //  88
    const char *TireSpewEmitterGroup;        //  92
    float       TireSpewMinSpeed;            //  96
    float       TireSpewMaxSpeed;            // 100
    const char *BottomOutEmitterGroup;       // 104
    float       BottomOutMinImpact;          // 108
    float       BottomOutMaxImpact;          // 112
    const char *CollisionImpactEmitterGroup; // 116
    float       CollisionImpactMinForce;     // 120
    float       CollisionImpactMaxForce;     // 124
    const char *CollisionScrapeEmitterGroup; // 128
    float       CollisionScrapeMinSpeed;     // 132
    float       CollisionScrapeMaxSpeed;     // 136
} TerrainTypeInfo;                           // 140

// Nine pointers on a 64-bit host where the PS2 had one word each, and two
// of them land four bytes past an eight-byte boundary and take an
// alignment pad on the way past: SkidTextureName after the two bytes at
// 12, and DriveOverEmitterGroup after DebugTopologyColour. So the slack
// count is 1 at NameHash; 2 at SkidTextureName (its pad); 3 from
// RoadNoiseGridSpacingInverse (its widening); 4 at DriveOverEmitterGroup
// (the second pad); and one more past each emitter group after that --
// 5 through 11. The last float ends exactly on a pointer boundary.
#define TERRAININFO_SLACK ((size_t)(sizeof(void *) - 4))

// 140 bytes on the handheld; 184 on a 64-bit host.
#define TERRAININFO_SIZEOF                                                  \
    ((size_t)((140 + 11 * TERRAININFO_SLACK + sizeof(void *) - 1)           \
              / sizeof(void *) * sizeof(void *)))

#ifndef TERRAINTYPE_NO_ASSERT
typedef char terraininfo_layout_check[
    (offsetof(TerrainTypeInfo, NameHash) == 4 + 1 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, Type) == 8 + 1 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, ShouldTireMakeRoadSound)
            == 12 + 1 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, ShouldCameraGoThroughIt)
            == 13 + 1 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, SkidTextureName)
            == 16 + 2 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, RoadNoiseGridSpacingInverse)
            == 20 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, RoadNoiseScale)
            == 24 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, StaticFrictionMultiplier)
            == 28 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, DynamicFrictionMultiplier)
            == 32 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, RollingFrictionMultiplier)
            == 36 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, DebugTopologyColour)
            == 52 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, DriveOverEmitterGroup)
            == 56 + 4 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, DriveOverMinSpeed)
            == 60 + 5 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, DriveOver2EmitterGroup)
            == 68 + 5 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, SkidSmokeEmitterGroup)
            == 80 + 6 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, TireSpewEmitterGroup)
            == 92 + 7 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, BottomOutEmitterGroup)
            == 104 + 8 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, CollisionImpactEmitterGroup)
            == 116 + 9 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, CollisionScrapeEmitterGroup)
            == 128 + 10 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, CollisionScrapeMaxSpeed)
            == 136 + 11 * TERRAININFO_SLACK
     && sizeof(TerrainTypeInfo) == TERRAININFO_SIZEOF) ? 1 : -1];
#endif

// 0x00310a90. Writable: the static init fills in the hashes.
extern TerrainTypeInfo TerrainTypeInfoTable[NUM_TERRAIN_TYPES];

// 0x001ca078. The terrain whose name matches, ignoring case; 0 (NONE) for
// NULL or no match.
int32_t terrain_match_name(const char *name);

// 0x001ca0e8. The terrain whose NameHash matches; 0 for no match -- which
// is every name before terraintype_static_init has run.
int32_t terrain_match_hash(uint32_t hash);

// 0x001ca120, _GLOBAL_$I$TerrainTypeInfoTable [66]: NameHash =
// bStringHash(Name) for all 33.
void terraintype_static_init(void);

#endif // TERRAINTYPE_H
