// track -- the rest of Track.obj (0x0014e7d0 .. 0x001509d4): position
// markers, the track info table, road noise, and the bundle loader that
// hands the topology its chunks. The collision surface itself is
// topology.h's.
//
// Written up in docs/formats/topology.md.

#ifndef TRACK_H
#define TRACK_H

#include <stdint.h>

#include "bvector.h"
#include "topology.h"

// ------------------------------------------------------------ the markers

// 24 bytes, chunk 0x34146: named points on the track -- the start grid,
// the finish, the cop spawns -- that the loader links in place, so the
// chunk is read-write and outlives its own list entries.
typedef struct TrackPositionMarker {
    TrackListNode node;        //  0
    uint32_t      NameHash;    //  8  bStringHash of the name
    int32_t       Param;       // 12
    bVector2      Position;    // 16
} TrackPositionMarker;         // 24

// 0x00323410. The list head.
extern TrackListNode TrackPositionMarkerList;

// 0x0014e7d0 / 0x0014e810. How many markers carry `hash`, and the i-th of
// them in load order (NULL past the last).
int track_get_num_position_markers(uint32_t hash);
TrackPositionMarker *track_get_position_marker(uint32_t hash, int i);

// 0x0014e858 / 0x0014e880. The same, hashing a name first.
int track_get_num_position_markers_named(const char *name);
TrackPositionMarker *track_get_position_marker_named(const char *name, int i);

// ------------------------------------------------------------ TrackInfo

// 164 bytes, retail's TrackInfo. Chunk 0x34201 (GLOBALB) is the table of
// every track, 0x34200 the loaded one's own copy. No pointers, so both are
// read in place, and the layout is the disc's: retail's GetTrackInfo
// (0x00153420) and LoaderTrackGeometry (0x00153608) step by 164, where
// the demo's (and the .mdebug's) record is 160.
//
// Retail put SignpostGracePeriod in before SoundRegion. Its one reader is
// retail's AICarController::SignPostDecision (0x00191efc): -1 keeps the
// demo's test, Race::GracePeriodIsActive, and anything else is a race
// time in seconds the AI must be past before it takes any sign but
// AlwaysTake. Retail's thirty tracks have -1 but for T23, T26, T42 and
// T45, which have 0.
typedef struct TrackInfo {
    char     Name[32];                           //   0
    char     Location[32];                       //  32
    int8_t   IsValid;                            //  64
    int8_t   TrackNumber;                        //  65
    int8_t   SameAsTrackNumber;                  //  66
    int8_t   Point2Point;                        //  67
    int16_t  TimeOfDay;                          //  68
    int16_t  HighScoreIndex;                     //  70
    int32_t  TrackLanguageID;                    //  72
    int32_t  ReverseTrackLanguageID;             //  76
    float    Length;                             //  80
    uint32_t CopCharacterNameHash;               //  84
    uint32_t SuperCopCharacterNameHash;          //  88
    bVector2 TrackMapCalibrationUpperLeft;       //  92
    float    TrackMapCalibrationMapWidthMetres;  // 100
    uint16_t TrackMapCalibrationRotation;        // 104
    uint16_t TrackMapStartLineAngle;             // 106
    uint16_t TrackMapFinishLineAngle;            // 108
    uint8_t  _pad0[2];                           // 110
    float    MinElevation;                       // 112
    float    MaxElevation;                       // 116
    int32_t  Difficulty;                         // 120
    int32_t  OverrideStartingRouteForAI;         // 124
    int32_t  SignpostGracePeriod;                // 128  retail's
    char     SoundRegion[32];                    // 132
} TrackInfo;                                     // 164

typedef char trackinfo_layout_check[
    (sizeof(TrackInfo) == 164 && sizeof(TrackPositionMarker) == 24) ? 1 : -1];

// 0x00323428 / 0x0032342c / 0x00323430 / 0x00323434.
extern TrackInfo *CurrentTrackInfo;
extern TrackInfo *TrackInfoTable;
extern int32_t    HighestTrackNumber;
extern int32_t    LoadedTrackNumber;

// 0x00150478. Track `i`, counting from 1, or NULL when it is out of range
// or its entry has no name.
TrackInfo *track_get_info(int i);

// ------------------------------------------------------------ road noise

// 0x002f14f0. Sixteen values in [-0.5, 0.5].
extern const float RoadNoiseTable[16];

// 0x001504b0. A hash of the grid point into RoadNoiseTable.
float track_get_road_noise_grid_value(int x, int y);

// 0x001504f0. Bilinear over the terrain's grid (TerrainTypeInfo's
// RoadNoiseGridSpacingInverse), scaled by its RoadNoiseScale.
float track_get_road_noise(const bVector2 *p, int32_t terrain);

// ------------------------------------------------------------ the loader

// 0x00150660 / 0x00150770. One chunk of the track bundle, header and all.
// 1 when it was one of the seven this object owns.
int track_loader_geometry(uint8_t *chunk);
int track_unloader_geometry(const uint8_t *chunk);

// 0x00150938, _GLOBAL_$I$TrackPositionMarkerList [22]: the marker list
// empty and TheTopologyTree empty. Its partner _GLOBAL_$D$ (0x00150908) is
// not ported -- it runs at exit, which the handheld never reaches, and
// would bFree every marker, which lives in chunk memory.
void track_static_init(void);

#endif // TRACK_H
