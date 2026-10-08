// copmanager -- tCopManager, the cops' records and the chunks they load
// from, and the queries the HUD, the cameras and the AI make of them.
//
// tCopManager is retail's copmgr.obj (0x002235f8 .. 0x00228fc8). The demo's
// is 10472 bytes (.mdebug type#5615); retail's is 10516, with a word at the
// front, six pursuit slots and a word after PursuitList, and four words
// near the end. The layout below is retail's, checked on a 32-bit target.
//
// This file and copmanager.c keep what other code reads: the records, the
// pointer, and the small queries (copmanager.c links into many checkers,
// so it stays free of the track). The manager's building and running are
// copmgr.c's, on copmgr.h.

#ifndef COPMANAGER_H
#define COPMANAGER_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "bvector.h"
#include "drivetarget.h"

struct Car;

typedef struct tCopManager tCopManager;
typedef struct tPursuit tPursuit;
typedef struct tCop tCop;

// ------------------------------------------------------- the cop chunks
//
// LoaderCops (0x00227dc0) takes the container 0x80034500 and keeps a
// pointer to each of its three children's data, which the manager reads
// in place: the radar traps (0x34510), the roadblock spots (0x34520) and
// the landmarks (0x34530). Each is a count, then the records.

// .mdebug type#2056, 32 bytes.
typedef struct RadarTrapInfo {
    char     Name[16];                  //  0
    bVector2 Centre;                    // 16
    int32_t  BeACopSpawnSpot;           // 24  Be A Cop starts here
    int32_t  BeACopReverseSpawnSpot;    // 28  and here run backwards
} RadarTrapInfo;

// type#2062. Traps[NumRadarTraps].
typedef struct RadarTrapChunk {
    uint32_t      NumRadarTraps;        //  0
    RadarTrapInfo Traps[1];             //  4
} RadarTrapChunk;

// type#2072, 28 bytes. The bitfields share the word at 24, LSB first;
// the bits above 6 are whatever the tool left there.
typedef struct RoadblockInfo {
    char     Name[16];                  //  0
    bVector2 Centre;                    // 16
    uint32_t Bits;                      // 24
} RoadblockInfo;

#define ROADBLOCKINFO_DIRECTION(b)   ((b) & 3u)          // 0 both, 1 fwd, 2 rev
#define ROADBLOCKINFO_SPIKESIDE(b)   (((b) >> 2) & 3u)
#define ROADBLOCKINFO_DIFFICULTY(b)  (((b) >> 4) & 3u)
#define ROADBLOCKINFO_CLOSURE(b)     (((b) >> 6) & 1u)   // RoadClosureSpot

// type#2078. Roadblocks[NumRoadblocks].
typedef struct RoadblockInfoChunk {
    uint32_t      NumRoadblocks;        //  0
    RoadblockInfo Roadblocks[1];        //  4
} RoadblockInfoChunk;

// type#2042, 60 bytes: an area of the track by a polygon.
typedef struct Landmark {
    int32_t  NumVerts;                  //  0
    bVector2 VertsForArea[6];           //  4
    int32_t  LandmarkType;              // 52  what the cops call it
    int32_t  IsUncloakTrigger;          // 56
} Landmark;

// type#2049. LandmarkArray[NumLandmarks].
typedef struct LandmarkChunk {
    uint32_t NumLandmarks;              //  0
    Landmark LandmarkArray[1];          //  4
} LandmarkChunk;

typedef char landmark_size_check[sizeof(Landmark) == 60 ? 1 : -1];
typedef char radartrapinfo_size_check[sizeof(RadarTrapInfo) == 32 ? 1 : -1];
typedef char roadblockinfo_size_check[sizeof(RoadblockInfo) == 28 ? 1 : -1];

// tCopManager's statics, gp-15656, gp-15652 and gp-15648 (0x00331bc8,
// 0x00331bcc, 0x00331bd0): the chunks' data, NULL with no chunk.
extern LandmarkChunk      *LandmarkData;
extern RadarTrapChunk     *SpeedTrapData;
extern RoadblockInfoChunk *RoadblockData;

// ---------------------------------------------------------- the records

struct stAICop;
struct TrackRoute;
struct TrackRoutePoint;

// type#2424, 120 bytes: a spot a roadblock can be set at. The manager
// keeps one for each usable RoadblockInfo; a pursuit points at the one it
// called.
typedef struct tRoadBlock {
    struct stAICop *cops[2];            //   0  NULL for none
    bVector4 pos;                       //   8
    int32_t  ang;                       //  24
    uint16_t aTrackMapIconAngle;        //  28  a BAM
    uint16_t Pad30;                     //  30
    const RoadblockInfo *Name;          //  32  the record, whose name leads
    struct TrackRoutePoint *RoutePoint; //  36
    struct TrackRoute *Route;           //  40
    float    fRoadWidth;                //  44  the point's two widths
    int32_t  nSpikeSide;                //  48
    bVector2 v2SpikeBeltPos;            //  52
    bVector2 v2SpikeBeltVec;            //  60
    bVector2 v2Position;                //  68  on the road at the record
    bVector2 D;                         //  76  along the road
    bVector2 L;                         //  84  across it, D turned right
    bVector2 v2EscapeLane;              //  92
    float    fDistanceAroundTrack;      // 100
    int32_t  nIndexIntoLoadedData;      // 104
    int32_t  Difficulty;                // 108
    uint32_t Flags;                     // 112  1: a road closure
    uint32_t CopSpeaker;                // 116
} tRoadBlock;                           // 120

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char troadblock_layout_check[
    (offsetof(tRoadBlock, pos) == 8
     && offsetof(tRoadBlock, aTrackMapIconAngle) == 28
     && offsetof(tRoadBlock, Name) == 32
     && offsetof(tRoadBlock, RoutePoint) == 36
     && offsetof(tRoadBlock, Route) == 40
     && offsetof(tRoadBlock, v2SpikeBeltPos) == 52
     && offsetof(tRoadBlock, v2Position) == 68
     && offsetof(tRoadBlock, D) == 76
     && offsetof(tRoadBlock, v2EscapeLane) == 92
     && offsetof(tRoadBlock, fDistanceAroundTrack) == 100
     && offsetof(tRoadBlock, CopSpeaker) == 116
     && sizeof(tRoadBlock) == 120) ? 1 : -1];
#endif

// type#5556, 28 bytes: a radar trap's spot.
typedef struct tSpeedTrap {
    tCop    *cop;                       //  0  the cop sitting in it, or NULL
    bVector2 v2Position;                //  4
    uint16_t ang;                       // 12  the road's heading, a BAM
    uint16_t Pad14;                     // 14
    const RadarTrapInfo *Name;          // 16  the record, whose name leads
    float    fDistanceAroundTrack;      // 20
    uint32_t Flags;                     // 24  1 Be A Cop's, 2 reversed
} tSpeedTrap;                           // 28

#define SPEEDTRAP_BEACOP          1u
#define SPEEDTRAP_BEACOP_REVERSE  2u

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char tspeedtrap_layout_check[
    (offsetof(tSpeedTrap, ang) == 12 && offsetof(tSpeedTrap, Name) == 16
     && sizeof(tSpeedTrap) == 28) ? 1 : -1];
#endif

// eLogicState, .mdebug t1052.
typedef int32_t eLogicState;
#define LS_INVALID          ((eLogicState)0)
#define LS_LIMBO            ((eLogicState)1)
#define LS_DISABLED         ((eLogicState)2)
#define LS_SPEED_TRAP       ((eLogicState)3)
#define LS_ROAD_BLOCK       ((eLogicState)4)
#define LS_DRIVING_ON_PATROL ((eLogicState)5)
#define LS_HOT_PURSUIT      ((eLogicState)6)
#define LS_CAUGHT_SPEEDER   ((eLogicState)7)
#define LS_GUARD_LOCATION   ((eLogicState)8)

// eLogicSubState, .mdebug L52663.
typedef int32_t eLogicSubState;
#define LSS_NONE                     ((eLogicSubState)0)
#define LSS_PURSUIT_FOLLOW           ((eLogicSubState)1)
#define LSS_FOLLOW_OFFSET            ((eLogicSubState)2)
#define LSS_LOW_SPEED_CLOSE_FOLLOW   ((eLogicSubState)3)
#define LSS_FOLLOW_BACKWARDS         ((eLogicSubState)4)
#define LSS_FLANK                    ((eLogicSubState)5)
#define LSS_BUMP                     ((eLogicSubState)6)
#define LSS_BLOCK                    ((eLogicSubState)7)
#define LSS_GET_AHEAD                ((eLogicSubState)8)
#define LSS_ACQUIRE                  ((eLogicSubState)9)
#define LSS_STOP                     ((eLogicSubState)10)
#define LSS_LIMBO_DISABLED           ((eLogicSubState)11)
#define LSS_LIMBO_READY              ((eLogicSubState)12)
#define LSS_CAUGHTSPEEDER_TICKETING  ((eLogicSubState)13)
#define LSS_CAUGHTSPEEDER_WAITING    ((eLogicSubState)14)

// type#5558, 32 bytes: tCop, the base of tAICop and tPlayerCop. The
// vptr is the image's table address (vtable.h): 8 the destructor, 16
// IsAIControlled (pure here; tAICop's 1, tPlayerCop's 0), 24 Think, 32
// DoSnapshot.
struct tCop {
    tPursuit      *pMyPursuit;          //  0 NULL while not chasing
    struct Car    *pMyCar;              //  4
    int32_t        nCopNumber;          //  8
    eLogicState    LogicState;          // 12
    eLogicState    DesiredLogicState;   // 16
    eLogicSubState LogicSubState;       // 20
    eLogicSubState DesiredLogicSubState;// 24
    uint32_t       vptr;                // 28
};

#define TCOP_VT_DTOR              8
#define TCOP_VT_IS_AI_CONTROLLED  16
#define TCOP_VT_THINK             24
#define TCOP_VT_SNAPSHOT          32

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char tcop_layout_check[
    (offsetof(struct tCop, pMyCar) == 4
     && offsetof(struct tCop, DesiredLogicState) == 16
     && offsetof(struct tCop, vptr) == 28 && sizeof(struct tCop) == 32)
    ? 1 : -1];
#endif

// bTNode<tPursuit>: a pursuit's links in the manager's PursuitList. The
// list's own node is the sentinel, so the last pursuit's Next is the list.
// bTList<tSpikeStrip> is the same two words.
typedef struct tPursuitNode {
    struct tPursuitNode *Next;          //  0
    struct tPursuitNode *Prev;          //  4
} tPursuitNode;

// tPursuitHistory, retail's 368 bytes (new in retail; the constructor is
// 0x0022cee0, the table 0x002bd470): the chased car's last 30 velocities,
// newest first, and the seconds each lasted. Update (0x0022cf90) shifts
// them down a place and puts the newest at 0; nCount climbs to 30.
// VelocityAt (0x0022d080) reads it.
typedef struct tPursuitHistory {
    int32_t  nCount;                    //   0
    bVector2 v2Velocity[30];            //   4
    float    fTime[30];                 // 244
    uint32_t vptr;                      // 364  0x002bd470
} tPursuitHistory;                      // 368

#define TPURSUITHISTORY_VTABLE 0x002bd470u

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char tpursuithistory_layout_check[
    (offsetof(tPursuitHistory, fTime) == 244
     && offsetof(tPursuitHistory, vptr) == 364
     && sizeof(tPursuitHistory) == 368) ? 1 : -1];
#endif

// ePursuitState, .mdebug t3282.
typedef int32_t ePursuitState;
#define EPS_LEVEL0                 ((ePursuitState)0)
#define EPS_LEVEL1                 ((ePursuitState)1)
#define EPS_LEVEL2                 ((ePursuitState)2)
#define EPS_LEVEL3                 ((ePursuitState)3)
#define EPS_SPEEDER_CAUGHT         ((ePursuitState)4)
#define EPS_END_PURSUIT_GIVE_UP    ((ePursuitState)5)

// eChopperState, .mdebug t3285.
typedef int32_t eChopperState;
#define ECS_NO_CHOPPER             ((eChopperState)0)
#define ECS_CHOPPER_REQUESTED      ((eChopperState)1)
#define ECS_CHOPPER_INFLIGHT       ((eChopperState)2)
#define ECS_CHOPPER_ATTACKING      ((eChopperState)3)

// The demo's type#1640 is 1216 bytes; retail's is 1600 (its slot pool's
// slot), and these are the words read so far, at retail's offsets on a
// 32-bit target. The demo's nHUDPursuitLevel was at 1112.
struct tPursuit {
    tPursuitNode Node;                  //    0
    uint8_t     Unported8[8];           //    8
    struct Car *pChasedCar;             //   16, the demo's 20
    tRoadBlock *pRoadBlock;             //   20, the demo's 24; NULL for none
    uint8_t     Unported24[24];         //   24
    // The constructor's (0x00228fc8): the points ahead of the chased car,
    // which CopDriver steers along when it is far from it, and the ones
    // right behind it, which it takes when within 20 m. The pursuit's Think
    // fills both.
    DriveTarget FarDriveTarget;         //   48
    DriveTarget NearDriveTarget;        //  576
    tPursuitHistory History;            // 1104 the chased car's velocities
    uint8_t     Unported1472[8];        // 1472
    // Retail's: the manager's PursuitsById slot, from 0x002244a0.
    int8_t      nPursuitId;             // 1480
    uint8_t     Unported1481[3];        // 1481
    // The demo's fields from 1104 on are here 380 bytes later.
    ePursuitState PursuitState;         // 1484, the demo's 1104
    uint8_t     Unported1488[4];        // 1488
    int32_t     nHUDPursuitLevel;       // 1492  the HUD's pursuit meter
    uint8_t     Unported1496[28];       // 1496
    float       fPursuitStateTimer;     // 1524, the demo's 1144
    uint8_t     Unported1528[4];        // 1528
    float       fRoadBlockSpawnTimer;   // 1532, the demo's 1152
    uint8_t     Unported1536[24];       // 1536
    // Retail's. RenderHud lights one more Be The Cop roadblock, in the
    // "on its way" colour, while it is set.
    int32_t     New1560;                // 1560
    uint8_t     Unported1564[16];       // 1564
    eChopperState ChopperState;         // 1580, the demo's 1196
    uint8_t     Unported1584[8];        // 1584
    uint32_t    vptr;                   // 1592  0x002bd460: 8 the destructor
    uint8_t     Unported1596[4];        // 1596
};

#define TPURSUIT_VT_DTOR  8

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char tpursuit_layout_check[
    (offsetof(struct tPursuit, pChasedCar) == 16
     && offsetof(struct tPursuit, pRoadBlock) == 20
     && offsetof(struct tPursuit, FarDriveTarget) == 48
     && offsetof(struct tPursuit, NearDriveTarget) == 576
     && offsetof(struct tPursuit, History) == 1104
     && offsetof(struct tPursuit, nPursuitId) == 1480
     && offsetof(struct tPursuit, PursuitState) == 1484
     && offsetof(struct tPursuit, nHUDPursuitLevel) == 1492
     && offsetof(struct tPursuit, fPursuitStateTimer) == 1524
     && offsetof(struct tPursuit, fRoadBlockSpawnTimer) == 1532
     && offsetof(struct tPursuit, New1560) == 1560
     && offsetof(struct tPursuit, ChopperState) == 1580
     && offsetof(struct tPursuit, vptr) == 1592
     && sizeof(struct tPursuit) == 1600) ? 1 : -1];
#endif

// tSpikeStrip, 2304 bytes in retail: a stinger on the road, in the
// manager's SpikeStripList. Its links and its table so far.
typedef struct tSpikeStrip {
    tPursuitNode Node;                  //    0
    uint8_t     Unported8[2280];        //    8
    uint32_t    vptr;                   // 2288  8 the destructor
    uint8_t     Unported2292[12];       // 2292
} tSpikeStrip;

#define TSPIKESTRIP_VT_DTOR  8

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char tspikestrip_layout_check[
    (offsetof(tSpikeStrip, vptr) == 2288 && sizeof(tSpikeStrip) == 2304)
    ? 1 : -1];
#endif

// tCarPulloverInfo (type#5538), 28 bytes: a car a cop has pulled over.
typedef struct tCarPulloverInfo {
    int32_t nCopIndex;                    //  0
    float   fHoldTimer;                   //  4
    int8_t  nNumTickets;                  //  8
    int32_t bActive;                      // 12
    int32_t bPlayNIS;                     // 16
    int32_t bArrest;                      // 20
    int32_t bShouldDisplayBustedText;     // 24
} tCarPulloverInfo;

typedef char tcarpulloverinfo_size_check[
    sizeof(tCarPulloverInfo) == 28 ? 1 : -1];

// Deque<unsigned int,4> (type#5604), 28 bytes: the speakers' voice ids,
// popped from the head and pushed back at the tail. Full tells a full
// ring from an empty one, both with Head == Tail.
typedef struct CopSpeakerDeque {
    uint32_t Data[4];                   //  0
    int32_t  Head;                      // 16
    int32_t  Tail;                      // 20
    int32_t  Full;                      // 24
} CopSpeakerDeque;

#define COPMANAGER_MAX_COPS          7
#define COPMANAGER_MAX_PURSUITS      6
#define COPMANAGER_NUM_PULLOVERS     8
#define COPMANAGER_MAX_ROADBLOCKS    64
#define COPMANAGER_MAX_SPEEDTRAPS    64
#define COPMANAGER_NUM_CARS          14

// ---------------------------------------------------------- tCopManager

struct tCopManager {
    int32_t   nBeACopNumRoadBlocks;     //     0  the demo's 10456
    int32_t   nNumAICops;               //     4
    int32_t   nNumCops;                 //     8
    int32_t   nPlayerCopIndex;          //    12  -1 for none
    tCop     *Cops[COPMANAGER_MAX_COPS];//    16
    tPursuitNode PursuitList;           //    44  bTList<tPursuit>
    // Retail's: each pursuit by its id, tPursuit's byte at 1480, which
    // 0x002244a0 hands out and 0x00224560 clears.
    tPursuit *PursuitsById[COPMANAGER_MAX_PURSUITS];  // 52
    tPursuit *New76;                    //    76  a pursuit, deleted first
    tPursuitNode SpikeStripList;        //    80  bTList<tSpikeStrip>
    tCarPulloverInfo CarPullovers[COPMANAGER_NUM_PULLOVERS];   // 88
    int32_t   bChopperBusy;             //   312
    int32_t   nNumRoadBlocks;           //   316
    tRoadBlock RoadBlocks[COPMANAGER_MAX_ROADBLOCKS];          // 320
    int32_t   RealRoadBlockIndexFromDataIndex[64];             // 8000
    int32_t   nNumSpeedTraps;           //  8256
    tSpeedTrap SpeedTraps[COPMANAGER_MAX_SPEEDTRAPS];          // 8260
    int32_t   RealSpeedTrapIndexFromDataIndex[64];             // 10052
    CopSpeakerDeque CopSpeakers;        // 10308
    uint32_t  BeACopId;                 // 10336
    float     TimeSinceLastSpeech;      // 10340
    float     MaxSpeechGapTime;         // 10344
    float     fSupervisorTimer;         // 10348
    uint32_t  SpeechFillerCookie;       // 10352
    float     fPursuableTimer[8];       // 10356
    float     fSpeedTrapSpawnTimer[8];  // 10388
    float     fCarDamage[COPMANAGER_NUM_CARS];                 // 10420
    int32_t   nDifficultyLevel;         // 10476  0, 1 or 2
    float     fBeACopTime;              // 10480  seconds
    int32_t   bBeACopAlreadySaidLookOutForSpeeders;            // 10484
    int32_t   New10488;                 // 10488
    int32_t   nBeACopNumChopperAttacks; // 10492
    int32_t   nBeACopNumArrestsMade;    // 10496
    int32_t   New10500;                 // 10500
    // Retail's (0x002276a0): the first cop car's Xdim and Ydim, x 1.1.
    float     fMaxCopCarXdim;           // 10504
    float     fMaxCopCarYdim;           // 10508
    uint32_t  vptr;                     // 10512  0x002bd280
};                                      // 10516

#define TCOPMANAGER_VTABLE  0x002bd280u
#define TCOPMANAGER_SIZE    10516

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char tcopmanager_layout_check[
    (offsetof(tCopManager, Cops) == 16
     && offsetof(tCopManager, PursuitList) == 44
     && offsetof(tCopManager, PursuitsById) == 52
     && offsetof(tCopManager, SpikeStripList) == 80
     && offsetof(tCopManager, CarPullovers) == 88
     && offsetof(tCopManager, bChopperBusy) == 312
     && offsetof(tCopManager, RoadBlocks) == 320
     && offsetof(tCopManager, RealRoadBlockIndexFromDataIndex) == 8000
     && offsetof(tCopManager, nNumSpeedTraps) == 8256
     && offsetof(tCopManager, SpeedTraps) == 8260
     && offsetof(tCopManager, RealSpeedTrapIndexFromDataIndex) == 10052
     && offsetof(tCopManager, CopSpeakers) == 10308
     && offsetof(tCopManager, BeACopId) == 10336
     && offsetof(tCopManager, fPursuableTimer) == 10356
     && offsetof(tCopManager, fCarDamage) == 10420
     && offsetof(tCopManager, nDifficultyLevel) == 10476
     && offsetof(tCopManager, nBeACopNumChopperAttacks) == 10492
     && offsetof(tCopManager, fMaxCopCarXdim) == 10504
     && offsetof(tCopManager, vptr) == 10512
     && sizeof(tCopManager) == TCOPMANAGER_SIZE) ? 1 : -1];
#endif

// gp-15620, 0x00331bec (the demo's gp-16500). NULL outside a race with
// cops.
extern tCopManager *pCopManager;

// The code written before the manager was whole reads its head through
// this name; it is the manager.
typedef tCopManager tCopManagerHead;

static inline tCopManagerHead *copmanager_head(tCopManager *m)
{
    return m;
}

// Be A Cop's player cop: Cops[nPlayerCopIndex], or NULL for -1. Retail
// then reads the cop's pMyCar with no test, through NULL when there is
// none; the port's callers test. A NULL manager has none here.
static inline tCop *copmanager_get_player_cop(tCopManager *m)
{
    if (m == NULL || m->nPlayerCopIndex == -1)
        return NULL;
    return m->Cops[m->nPlayerCopIndex];
}

// Byte offsets, for the harnesses that poke a manager by them.
#define COPMANAGER_PULLOVERS        offsetof(tCopManager, CarPullovers)
#define COPMANAGER_CHOPPER_BUSY     offsetof(tCopManager, bChopperBusy)
#define COPMANAGER_CAR_DAMAGE       offsetof(tCopManager, fCarDamage)
#define COPMANAGER_BEACOP_TIME      offsetof(tCopManager, fBeACopTime)
#define COPMANAGER_BEACOP_CHOPPERS  offsetof(tCopManager, \
                                             nBeACopNumChopperAttacks)

// The word at 960 of the World's Chopper that 0x00224ec0 wants 0 before
// a helicopter can be called (hudrender.c's can_call_helicopter).
#define CHOPPER_NEW960              960

static inline int32_t copmanager_word(const tCopManager *m, size_t off)
{
    int32_t v;

    memcpy(&v, (const uint8_t *)m + off, sizeof v);
    return v;
}

static inline float copmanager_float(const tCopManager *m, size_t off)
{
    float v;

    memcpy(&v, (const uint8_t *)m + off, sizeof v);
    return v;
}

// tCopManager::ShouldDisplayBustedText, 0x002289f8: 1 if any pullover is
// active and has bShouldDisplayBustedText, the first such ending the
// search. The manager must be there.
int32_t copmanager_should_display_busted_text(const tCopManager *m);

// tCopManager::IsBeingPursued, 0x00227438: the first pursuit in
// PursuitList whose pChasedCar is `c`, or NULL.
tPursuit *copmanager_is_being_pursued(tCopManager *m, struct Car *c);

// tCopManager::GetPursuitLevelForHUD, 0x00227480: that pursuit's
// nHUDPursuitLevel, or 0 for none.
int32_t copmanager_get_pursuit_level_for_hud(tCopManager *m,
                                             struct Car *c);

// tCopManager::GetNumTickets, 0x00228520: the signed byte nNumTickets of
// CarPullovers[c->CarIndex], the index read as a short.
int32_t copmanager_get_num_tickets(tCopManager *m, struct Car *c);

// tCopManager::GetNumActiveRoadBlocks, 0x00226968: how many pursuits in
// PursuitList have a pRoadBlock.
int32_t copmanager_get_num_active_road_blocks(tCopManager *m);

// tCopManager::GetActiveRoadBlock, 0x00226238: the pRoadBlock of the
// i-th pursuit in PursuitList that has one, counting from 0, or NULL.
tRoadBlock *copmanager_get_active_road_block(tCopManager *m, int32_t i);

// tCopManager::GetCopByCar (0x00224f70), the cop driving `c`, and
// GetCopByChase (0x00224fc8), the cop chasing it. Seams until task 26; a
// NULL seam finds no cop.
extern tCop *(*gCopManagerGetCopByCarFn)(tCopManager *m, struct Car *c);
extern tCop *(*gCopManagerGetCopByChaseFn)(tCopManager *m, struct Car *c);

// 0x0022d080, the history's VelocityAt (new in retail): the velocity `t`
// seconds back. It walks the times from the newest, and in the first
// whose running total reaches `t` (unless it is the last kept) puts the
// velocity at the start of it plus its slope -- the change to the next
// older one over its own time -- times the total less the *newest* time,
// fTime[0], whichever entry it is. Past the end, or with nothing kept, it
// is the newest, v2Velocity[0], as it is when the last kept is the one.
bVector2 *tpursuithistory_velocity_at(bVector2 *out, const tPursuitHistory *h,
                                      float t);

// tPursuit::NotInChasingState, 0x002295c8: the speeder caught, or the
// pursuit given up.
int32_t tpursuit_not_in_chasing_state(const tPursuit *p);

// tPursuit::AboutToSaySomething, 0x0022b9e8: 1 while the cops have
// something of their own to say -- a roadblock spawn timer over 8,
// LEVEL0, LEVEL2's first 13 s, a blown tyre on the chased car (its
// BlownTireBits read as a signed byte), the pursuit's roadblock within
// 150 of it (`sqrt.s` of the squares summed x, then y), or a helicopter
// asked for. The chased car must be there.
int32_t tpursuit_about_to_say_something(const tPursuit *p);

#endif
