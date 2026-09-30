// terraintype -- retail's TerrainType.obj (0x001d4428 .. 0x001d4520; the
// demo's 0x001ca078 .. 0x001ca170) and its table.
//
// Every track polygon carries a terrain number (topology.h's
// TopologyTreePolygon.Type), and every consumer of that number -- Wheel's
// friction and skids, Track's road noise, the particle and sound systems --
// reads it back through TerrainTypeInfoTable, one 144-byte record per
// terrain (the demo's were 140). The table is data (0x00318c00, 33 entries)
// and terraintypetab.c carries it verbatim, written out of retail's ELF by
// tools/gen_terrain_table.py; the object's code is two lookups and the
// static initialiser that hashes the names, the demo's but for the stride.
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

// Retail's 144 bytes: the demo's `.mdebug` type#1584 with a float at 20,
// SkidWidthMultiplier, that MaybeMakeSkids (0x001a568c) multiplies into
// WheelInfo.Width. The name is the port's; retail has no stabs. It is 1.4
// on the loose surfaces and 1 elsewhere. The seven emitter groups are names --
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
    float       SkidWidthMultiplier;         //  20
    float       RoadNoiseGridSpacingInverse; //  24
    float       RoadNoiseScale;              //  28
    float       StaticFrictionMultiplier;    //  32
    float       DynamicFrictionMultiplier;   //  36
    float       RollingFrictionMultiplier;   //  40
    float       CollisionPriority;           //  44
    float       ForceMagnitude;              //  48
    float       ForceFrequency;              //  52
    uint32_t    DebugTopologyColour;         //  56
    const char *DriveOverEmitterGroup;       //  60
    float       DriveOverMinSpeed;           //  64
    float       DriveOverMaxSpeed;           //  68
    const char *DriveOver2EmitterGroup;      //  72
    float       DriveOver2MinSpeed;          //  76
    float       DriveOver2MaxSpeed;          //  80
    const char *SkidSmokeEmitterGroup;       //  84
    float       SkidSmokeMinSpeed;           //  88
    float       SkidSmokeMaxSpeed;           //  92
    const char *TireSpewEmitterGroup;        //  96
    float       TireSpewMinSpeed;            // 100
    float       TireSpewMaxSpeed;            // 104
    const char *BottomOutEmitterGroup;       // 108
    float       BottomOutMinImpact;          // 112
    float       BottomOutMaxImpact;          // 116
    const char *CollisionImpactEmitterGroup; // 120
    float       CollisionImpactMinForce;     // 124
    float       CollisionImpactMaxForce;     // 128
    const char *CollisionScrapeEmitterGroup; // 132
    float       CollisionScrapeMinSpeed;     // 136
    float       CollisionScrapeMaxSpeed;     // 140
} TerrainTypeInfo;                           // 144

// Nine pointers on a 64-bit host where the PS2 had one word each. Only one
// of them lands four bytes past an eight-byte boundary and takes an
// alignment pad on the way past: SkidTextureName, after the two bytes at
// 12. (The demo's DriveOverEmitterGroup took a second, but retail's float
// at 20 puts it on the boundary.) So the slack count is 1 at NameHash; 2 at
// SkidTextureName (its pad); 3 from SkidWidthMultiplier (its widening);
// and one more past each emitter group after that -- 4 through 10. The last
// float ends exactly on a pointer boundary.
#define TERRAININFO_SLACK ((size_t)(sizeof(void *) - 4))

// 144 bytes on the handheld; 184 on a 64-bit host.
#define TERRAININFO_SIZEOF                                                  \
    ((size_t)((144 + 10 * TERRAININFO_SLACK + sizeof(void *) - 1)           \
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
     && offsetof(TerrainTypeInfo, SkidWidthMultiplier)
            == 20 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, RoadNoiseGridSpacingInverse)
            == 24 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, RoadNoiseScale)
            == 28 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, StaticFrictionMultiplier)
            == 32 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, DynamicFrictionMultiplier)
            == 36 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, RollingFrictionMultiplier)
            == 40 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, DebugTopologyColour)
            == 56 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, DriveOverEmitterGroup)
            == 60 + 3 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, DriveOverMinSpeed)
            == 64 + 4 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, DriveOver2EmitterGroup)
            == 72 + 4 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, SkidSmokeEmitterGroup)
            == 84 + 5 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, TireSpewEmitterGroup)
            == 96 + 6 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, BottomOutEmitterGroup)
            == 108 + 7 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, CollisionImpactEmitterGroup)
            == 120 + 8 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, CollisionScrapeEmitterGroup)
            == 132 + 9 * TERRAININFO_SLACK
     && offsetof(TerrainTypeInfo, CollisionScrapeMaxSpeed)
            == 140 + 10 * TERRAININFO_SLACK
     && sizeof(TerrainTypeInfo) == TERRAININFO_SIZEOF) ? 1 : -1];
#endif

// 0x00318c00 (the demo's 0x00310a90). Writable: the static init fills in
// the hashes.
extern TerrainTypeInfo TerrainTypeInfoTable[NUM_TERRAIN_TYPES];

// 0x001d4428 (the demo's 0x001ca078). The terrain whose name matches,
// ignoring case; 0 (NONE) for NULL or no match.
int32_t terrain_match_name(const char *name);

// 0x001d4498 (the demo's 0x001ca0e8). The terrain whose NameHash matches;
// 0 for no match -- which is every name before terraintype_static_init has
// run.
int32_t terrain_match_hash(uint32_t hash);

// 0x001d44d0 (the demo's 0x001ca120), _GLOBAL_$I$TerrainTypeInfoTable
// [66]: NameHash = bStringHash(Name) for all 33.
void terraintype_static_init(void);

#endif // TERRAINTYPE_H
