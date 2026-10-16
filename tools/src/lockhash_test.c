// Checks lockhash.c (TASKS 37e) on the host, with bmath.c's draws.
//
// The port's alone, so there is no retail to diff against: the harness
// builds a World of its own (two players, two AI racers, two cops, two
// traffic cars and a helicopter), a Race and a coordinator, and checks:
//
//   - each part moves with every field it reads and with no other: a
//     change to each is made, the parts taken again, and exactly the
//     part's own must differ; the pointers, the tails, the engine
//     sound's RedLineSyncRPM, RelCoordMatrix while MatrixValid is 0 and
//     a RacingCar past NumRacingCars move none, the fields either side of
//     RedLineSyncRPM and of a stale RelCoordMatrix their own; a NULL
//     slot is told from the car
//     beside it; a range starting below 0 or ending past TotalNumCars is
//     the cars that are there; a NULL World is all 0;
//   - the fold moves with every bit of every part;
//   - lockhash_ran keeps the parts and logs them every NETSTEP_LOG_EVERY
//     frames, and lockhash_differs logs the window up to the frame once a
//     race, each frame's parts as ran and its draws: those between the
//     last frame's ran and its own, LOCKHASH_LINE to a line, with the
//     address each returned to; a frame not run, or not run since start,
//     not logged; nothing before start or after stop;
//   - each car's pieces: a change to a field moves its own slot's own
//     piece and no other; a pointer, the tail, the hole, RedLineSyncRPM
//     or RelCoordMatrix while MatrixValid is 0 none; a NULL
//     slot or one past TotalNumCars all 0; the clocks WorldTimer and
//     WorldLoopCounter; the window logs each frame's clocks and a word
//     for each slot, and the frame's own cars in pieces;
//   - bViewSeed: on a seed of its own from start, whose draws are not
//     the frame's and move no part, and on bDefaultSeed again after stop;
//   - bDefaultSeedWatch: told of bRandomI, bRandomF and bSetRandomSeed on
//     bDefaultSeed, with the address the draw returns to, and of no other
//     seed; the draws' values as without it.
//
// It prints a line for each fault and "total faults N" at the end.

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "car.h"
#include "cardriver.h"
#include "chopper.h"
#include "lockhash.h"
#include "race.h"
#include "racecoord.h"
#include "realtime.h"
#include "world.h"

// ------------------------------------------------------- what it reads

int32_t          WorldTimer;
int32_t          WorldLoopCounter;
Race*            pCurrentRace;
RaceCoordinator* pRaceCoordinator;

static uint16_t g_retail = 0x1234;

uint16_t world_calculate_debug_checksum(World* w)
{
    (void)w;
    return g_retail;
}

// ------------------------------------------------------------ the world

static World           g_world;
static Car             g_cars[8];
static CarDriver       g_drivers[8];
static struct Chopper  g_chopper;
static Race            g_race;
static RaceCoordinator g_rc;
static int             g_faults;
static const char*     g_what = "";

static void fault(const char* fmt, ...)
{
    va_list ap;

    printf("  FAULT [%s] ", g_what);
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    printf("\n");
    g_faults++;
}

// Every byte something, so a field the hash skips would show.
static void fill(void* p, size_t n, uint32_t seed)
{
    uint8_t* b = p;
    size_t   i;

    for (i = 0; i < n; i++) {
        seed = seed * 1664525u + 1013904223u;
        b[i] = (uint8_t)(seed >> 24);
    }
}

static void build(void)
{
    int i;

    memset(&g_world, 0, sizeof g_world);
    fill(&g_cars, sizeof g_cars, 1);
    fill(&g_chopper, sizeof g_chopper, 2);
    fill(&g_race, sizeof g_race, 3);
    fill(&g_rc, sizeof g_rc, 4);
    fill(&g_drivers, sizeof g_drivers, 5);
    for (i = 0; i < 8; i++) {
        g_world.CarTable[i] = &g_cars[i];
        g_race.RacingCarTable[i].pCar = &g_cars[i];
        g_cars[i].pCarDriver = &g_drivers[i];
        g_cars[i].State.MatrixValid = 1;
        g_drivers[i].MyDriveTarget.NumPoints = 3;
    }
    g_cars[7].pCarDriver = NULL;
    g_world.TotalNumCars  = 8;
    g_world.AICarPos      = 2;
    g_world.CopCarPos     = 4;
    g_world.TrafficCarPos = 6;
    g_world.Helicopter    = &g_chopper;
    g_world.fTimeToRemainPaused = 1.5f;
    g_world.PreviousTimeToWaste = 0.25f;
    g_world.fTimeScale          = 1.0f;
    g_world.fTimeScaleTimer     = 2.0f;
    g_world.TimeScaleCallbackParam = 7;
    g_world.WorldRandomSeed = 0x2468aceu;
    g_race.NumRacingCars = 4;
    WorldTimer   = 4000;
    bDefaultSeed = 0x12345678u;
    g_retail     = 0x1234;
    pCurrentRace     = &g_race;
    pRaceCoordinator = &g_rc;
}

// ------------------------------------------------------------ the parts

// A float's lowest bit flipped: a change whatever the random fill made it.
static void flip(float* f)
{
    uint8_t* b = (uint8_t*)f;

    b[0] ^= 1;
}

// A change made by `poke`, then the parts again: `want` the set of parts
// that must have moved (a bit each), and none other.
typedef void (*Poke)(void);

static Poke g_setup;

static void expect(const char* what, Poke poke, uint32_t want)
{
    LockHash a, b;
    int      i;

    g_what = what;
    build();
    if (g_setup) g_setup();
    lockhash_world(&g_world, &a);
    poke();
    lockhash_world(&g_world, &b);
    for (i = 0; i < LOCKHASH_PARTS; i++) {
        int moved = a.part[i] != b.part[i];
        int must  = (want >> i) & 1u;

        if (moved != must)
            fault("%s %s", kLockHashParts[i], moved ? "moved" : "did not move");
    }
    if (want && lockhash_fold(&a) == lockhash_fold(&b))
        fault("the fold did not move");
}

// Two worlds that must have the same parts.
static void same(const char* what, Poke one, Poke other)
{
    LockHash a, b;
    int      i;

    g_what = what;
    build();
    one();
    lockhash_world(&g_world, &a);
    build();
    other();
    lockhash_world(&g_world, &b);
    for (i = 0; i < LOCKHASH_PARTS; i++)
        if (a.part[i] != b.part[i]) fault("%s differs", kLockHashParts[i]);
}

#define T  (1u << LOCKHASH_TIME)
#define SD (1u << LOCKHASH_SEEDS)
#define PL (1u << LOCKHASH_PLAYERS)
#define RC (1u << LOCKHASH_RACERS)
#define CP (1u << LOCKHASH_COPS)
#define TR (1u << LOCKHASH_TRAFFIC)
#define RA (1u << LOCKHASH_RACE)

static void pTimer(void) { WorldTimer++; }
static void pPaused(void) { g_world.fTimeToRemainPaused += 1.0f; }
static void pWaste(void) { g_world.PreviousTimeToWaste += 1.0f; }
static void pScale(void) { g_world.fTimeScale = 0.5f; }
static void pScaleTimer(void) { g_world.fTimeScaleTimer += 1.0f; }
static void pScaleParam(void) { g_world.TimeScaleCallbackParam++; }
static void pRetail(void) { g_retail ^= 1; }
static void pCallback(void) { g_world.TimeScaleCallback = (void (*)(int32_t))1; }
static void pDefault(void) { bDefaultSeed ^= 0x100; }
static void pWorldSeed(void) { g_world.WorldRandomSeed ^= 1; }
static void pTeleporter(void) { g_world.Teleporter = (void*)&g_world; }
static void pPlayerPos(void) { flip(&g_cars[1].State.GeometryPosition.x); }
static void pPlayerMoved(void) { flip(&g_cars[0].State.DistanceMoved); }
static void pPlayerMode(void) { g_cars[0].TheControlMode ^= 1; }
static void pPlayerMove(void) { g_cars[1].TheMovementMode ^= 1; }
static void pPlayerInfo(void) { g_cars[0].State.pCarInfo = NULL; }
static void pPlayerTopo(void) { g_cars[0].State.pTopologyCoordinate = NULL; }
static void pPlayerTail(void) { g_cars[0].State._tail[3] ^= 1; }
static void pPlayerHole(void) { g_cars[0].State._hole8[0] ^= 1; }
static void pPlayerIndex(void) { g_cars[0].CarIndex ^= 1; }
static void pPlayerSlots(void)
{
    Car* t = g_world.CarTable[0];

    g_world.CarTable[0] = g_world.CarTable[1];
    g_world.CarTable[1] = t;
}
static void pRacerSpeed(void) { flip(&g_cars[2].State.ForwardSpeed); }
static void pRacerGear(void) { g_cars[3].State.CurrentGear ^= 1; }
static void pRacersFewer(void) { g_world.CopCarPos = 3; }
static void pCopRpm(void) { flip(&g_cars[4].State.RPM); }
static void pPlayerRedLine(void) { flip(&g_cars[1].State.RedLineSyncRPM); }
static void pRacerRedLine(void) { flip(&g_cars[2].State.RedLineSyncRPM); }
static void pPlayerClutch(void) { g_cars[0].State.ClutchEngaged ^= 1; }
static void pCopMatrix(void) { flip(&g_cars[5].State.RelCoordMatrix.v0.x); }
static void pPlayerMatrix(void) { flip(&g_cars[1].State.RelCoordMatrix.v0.x); }
static void pPlayerMatrixEnd(void) { flip(&g_cars[0].State.RelCoordMatrix.v3.w); }
static void pPlayerBurnOut(void) { flip(&g_cars[0].State.BurnOutAllow); }
static void pPlayerMovedToo(void) { flip(&g_cars[1].State.DistanceMoved); }
static void pPlayerValid(void) { g_cars[0].State.MatrixValid ^= 1; }
// Every car's matrix stale, as after its mover's step.
static void pStale(void)
{
    int i;

    for (i = 0; i < 8; i++) g_cars[i].State.MatrixValid = 0;
}
static void pTrafficWheel(void) { flip(&g_cars[6].State.WheelAngle[3]); }
static void pTrafficGone(void) { g_world.TotalNumCars = 7; }
static void pTrafficNull(void) { g_world.CarTable[7] = NULL; }
static void pTrafficNullMoved(void)
{
    g_world.CarTable[7] = g_world.CarTable[6];
    g_world.CarTable[6] = NULL;
}
static void pAIBelow(void) { g_world.AICarPos = -1; }
static void pAIZero(void) { g_world.AICarPos = 0; }
static void pTrafficPast(void)
{
    g_world.TotalNumCars  = 6;
    g_world.TrafficCarPos = 7;
}
static void pTrafficAtEnd(void)
{
    g_world.TotalNumCars  = 6;
    g_world.TrafficCarPos = 6;
}
static void pThink(void) { flip(&g_chopper.TimeUntilThink); }
static void pPlan(void) { g_chopper.Plan ^= 1; }
static void pMoveMode(void) { g_chopper.MoveMode ^= 1; }
static void pTargetDistance(void) { flip(&g_chopper.TargetDistance); }
static void pBombRun(void) { g_chopper.BombRunType ^= 1; }
static void pChopperPos(void) { flip(&g_chopper.CurrentPos.y); }
static void pNew960(void) { g_chopper.New960 ^= 1; }
static void pChopperCar(void) { g_chopper.CurrentCar = NULL; }
static void pChopperRoute(void) { g_chopper.ChopperRoute = NULL; }
static void pChopperPad(void) { g_chopper._pad964[0] ^= 1; }
static void pNoChopper(void) { g_world.Helicopter = NULL; }
static void pStage(void) { g_race.RaceStage ^= 1; }
static void pOneLeft(void) { g_race.DetectedOneCarRemaining ^= 1; }
static void pLaps(void) { g_race.NumLapsInRace++; }
static void pForcePos(void) { g_race.ForceRaceFinishPosition++; }
static void pForcePlayer(void) { g_race.ForceRaceFinishPlayerNum++; }
static void pRegion(void) { g_race.RacingCarTable[0].CurrentBoundaryRegion++; }
static void pAverage(void) { flip(&g_race.RacingCarTable[3].AverageSpeed); }
static void pPastRacing(void) { g_race.RacingCarTable[4].NumLapsCompleted++; }
static void pRacingCar(void) { g_race.RacingCarTable[0].pCar = NULL; }
static void pRacingFewer(void) { g_race.NumRacingCars = 3; }
static void pBoundaries(void) { g_race.NumBoundaries++; }
static void pGhost(void) { g_race.GhostCarDataFilename[0] ^= 1; }
static void pNoRace(void) { pCurrentRace = NULL; }
static void pRcState(void) { g_rc.CurrentRCState ^= 1; }
static void pRcExec(void) { g_rc.RCExecutingMessage ^= 1; }
static void pRcCount(void) { g_rc.DisplayingCountdownNumber++; }
static void pRcBefore(void) { g_rc.BeforePauseRCState ^= 1; }
static void pRcPort(void) { g_rc.PausedJoystickPort ^= 1; }
static void pNoRc(void) { pRaceCoordinator = NULL; }

// ------------------------------------------------------------ the pieces

#define MO  LOCKHASH_MODES
#define PC  LOCKHASH_PLACE
#define MT  LOCKHASH_MOTION
#define BD  LOCKHASH_BODY
#define SP  LOCKHASH_SPIN
#define WM  LOCKHASH_WHEELMATS
#define WH  LOCKHASH_WHEELS
#define DR  LOCKHASH_DRIVE
#define RL  LOCKHASH_REL
#define DV  LOCKHASH_DRIVER
#define NONE (-1)

static void qGeometry(void) { flip(&g_cars[1].State.GeometryPosition.x); }
static void qPosition(void) { flip(&g_cars[2].State.Position.pad); }
static void qVelocity(void) { flip(&g_cars[2].State.Velocity.y); }
static void qAccel(void) { flip(&g_cars[3].State.Acceleration.pad); }
static void qBody(void) { flip(&g_cars[3].State.BodyMatrix.v0.x); }
static void qAngVel(void) { flip(&g_cars[4].State.AngularVelocity.x); }
static void qAngAcc(void) { flip(&g_cars[4].State.AngularAcceleration.pad); }
static void qWheelMat(void) { flip(&g_cars[5].State.WheelMatrix[0].v0.x); }
static void qBrakeMat(void) { flip(&g_cars[5].State.BrakeMatrix[3].v3.w); }
static void qWheelAV(void) { flip(&g_cars[6].State.WheelAngularVelocity[0]); }
static void qTraction(void) { flip(&g_cars[6].State.WheelTractionUsage[3]); }
static void qAngle(void) { g_cars[7].State.Angle ^= 1; }
static void qSteer(void) { g_cars[7].State.SteeringAngle ^= 1; }
static void qThrottle(void) { flip(&g_cars[0].State.Throttle); }
static void qBurnOut(void) { flip(&g_cars[0].State.BurnOutAllow); }
static void qRpm(void) { flip(&g_cars[3].State.RPM); }
static void qRedLine(void) { flip(&g_cars[3].State.RedLineSyncRPM); }
static void qClutch(void) { g_cars[3].State.ClutchEngaged ^= 1; }
static void qRel(void) { flip(&g_cars[1].State.RelCoordMatrix.v0.x); }
static void qRelEnd(void) { flip(&g_cars[1].State.RelCoordMatrix.v3.w); }
static void qValid(void) { g_cars[1].State.MatrixValid ^= 1; }
static void qMoved(void) { flip(&g_cars[2].State.DistanceMoved); }
static void qControl(void) { g_cars[3].TheControlMode ^= 1; }
static void qDrvSteer(void) { g_drivers[5].Steering ^= 1; }
static void qDrvThrottle(void) { flip(&g_drivers[2].Throttle); }
static void qDrvNitro(void) { g_drivers[3].NitroFlag ^= 1; }
static void qDrvPoint(void) { flip(&g_drivers[4].MyDriveTarget.Points[2].z); }
static void qDrvSpeed(void) { flip(&g_drivers[4].MyDriveTarget.CalculatedSpeed[0]); }
static void qDrvCount(void) { g_drivers[6].MyDriveTarget.NumPoints = 2; }
static void qDrvPast(void) { flip(&g_drivers[4].MyDriveTarget.Points[3].x); }
static void qDrvLane(void) { flip(&g_drivers[4].MyDriveTarget.Points[1].pad); }
static void qDrvSpeedPast(void) { flip(&g_drivers[4].MyDriveTarget.CalculatedSpeed[3]); }
static void qDrvRoute(void) { g_drivers[4].MyDriveTarget.TType ^= 1; }
static void qDrvNone(void) { g_cars[6].pCarDriver = NULL; }
static void qMovement(void) { g_cars[4].TheMovementMode ^= 1; }

// A change by `poke`: exactly slot `slot`'s piece `piece` must move, or
// nothing for NONE.
static void piece(const char* what, Poke poke, int slot, int pieceAt)
{
    LockHash a, b;
    int      i, k;

    g_what = what;
    build();
    if (g_setup) g_setup();
    lockhash_world(&g_world, &a);
    poke();
    lockhash_world(&g_world, &b);
    for (i = 0; i < LOCKHASH_CARS; i++)
        for (k = 0; k < LOCKHASH_FIELDS; k++) {
            int moved = a.car[i][k] != b.car[i][k];
            int must  = i == slot && k == pieceAt;

            if (moved != must)
                fault("slot %d's %s %s", i, kLockHashFields[k],
                      moved ? "moved" : "did not move");
        }
    if (a.clock[0] != b.clock[0] || a.clock[1] != b.clock[1])
        fault("the clocks moved");
}

static void pieces(void)
{
    LockHash h;
    int      i, k;

    piece("GeometryPosition", qGeometry, 1, PC);
    piece("Position", qPosition, 2, PC);
    piece("Velocity", qVelocity, 2, MT);
    piece("Acceleration", qAccel, 3, MT);
    piece("BodyMatrix", qBody, 3, BD);
    piece("AngularVelocity", qAngVel, 4, SP);
    piece("AngularAcceleration", qAngAcc, 4, SP);
    piece("WheelMatrix", qWheelMat, 5, WM);
    piece("BrakeMatrix", qBrakeMat, 5, WM);
    piece("WheelAngularVelocity", qWheelAV, 6, WH);
    piece("WheelTractionUsage", qTraction, 6, WH);
    piece("Angle", qAngle, 7, DR);
    piece("SteeringAngle", qSteer, 7, DR);
    piece("Throttle", qThrottle, 0, DR);
    piece("BurnOutAllow", qBurnOut, 0, DR);
    piece("RPM", qRpm, 3, DR);
    piece("RedLineSyncRPM", qRedLine, 3, NONE);
    piece("ClutchEngaged", qClutch, 3, DR);
    piece("RelCoordMatrix", qRel, 1, RL);
    piece("RelCoordMatrix's last lane", qRelEnd, 1, RL);
    piece("MatrixValid", qValid, 1, RL);
    piece("DistanceMoved", qMoved, 2, RL);
    g_setup = pStale;
    piece("RelCoordMatrix, not valid", qRel, 1, NONE);
    piece("RelCoordMatrix's last lane, not valid", qRelEnd, 1, NONE);
    piece("MatrixValid, from 0", qValid, 1, RL);
    piece("DistanceMoved, the matrix not valid", qMoved, 2, RL);
    piece("BurnOutAllow, the matrix not valid", qBurnOut, 0, DR);
    g_setup = NULL;
    piece("TheControlMode", qControl, 3, MO);
    piece("the driver's Steering", qDrvSteer, 5, DV);
    piece("the driver's Throttle", qDrvThrottle, 2, DV);
    piece("the driver's NitroFlag", qDrvNitro, 3, DV);
    piece("a target point", qDrvPoint, 4, DV);
    piece("a target speed", qDrvSpeed, 4, DV);
    piece("the target's NumPoints", qDrvCount, 6, DV);
    piece("a target point past NumPoints", qDrvPast, 4, NONE);
    piece("a target point's fourth lane", qDrvLane, 4, NONE);
    piece("a target speed past NumPoints", qDrvSpeedPast, 4, NONE);
    piece("the target's TType", qDrvRoute, 4, NONE);
    piece("no driver", qDrvNone, 6, DV);
    piece("TheMovementMode", qMovement, 4, MO);
    piece("pCarInfo", pPlayerInfo, 0, NONE);
    piece("pTopologyCoordinate", pPlayerTopo, 0, NONE);
    piece("the CarState's tail", pPlayerTail, 0, NONE);
    piece("the CarState's hole", pPlayerHole, 0, NONE);
    piece("CarIndex", pPlayerIndex, 0, NONE);

    g_what = "the slots";
    build();
    g_world.CarTable[6]  = NULL;
    g_world.TotalNumCars = 7;
    WorldTimer       = 1234;
    WorldLoopCounter = 100077;
    lockhash_world(&g_world, &h);
    for (i = 0; i < LOCKHASH_CARS; i++) {
        uint32_t any = 0;

        for (k = 0; k < LOCKHASH_FIELDS; k++) any |= h.car[i][k];
        if ((i < 7 && i != 6) != (any != 0))
            fault("slot %d %s", i, any ? "has pieces" : "has none");
    }
    if (h.clock[0] != 1234 || h.clock[1] != 100077)
        fault("the clocks %lu %lu", (unsigned long)h.clock[0],
              (unsigned long)h.clock[1]);
    memset(&h, 0xff, sizeof h);
    lockhash_world(NULL, &h);
    for (i = 0; i < LOCKHASH_CARS; i++)
        for (k = 0; k < LOCKHASH_FIELDS; k++)
            if (h.car[i][k] != 0) fault("no World: slot %d not 0", i);
    if (h.clock[0] != 0 || h.clock[1] != 0) fault("no World: clocks not 0");
}

static void parts(void)
{
    LockHash h;
    int      i;

    expect("WorldTimer", pTimer, T);
    expect("fTimeToRemainPaused", pPaused, T);
    expect("PreviousTimeToWaste", pWaste, T);
    expect("fTimeScale", pScale, T);
    expect("fTimeScaleTimer", pScaleTimer, T);
    expect("TimeScaleCallbackParam", pScaleParam, T);
    expect("retail's checksum", pRetail, T);
    expect("TimeScaleCallback", pCallback, 0);
    expect("bDefaultSeed", pDefault, SD);
    expect("WorldRandomSeed", pWorldSeed, SD);
    expect("Teleporter", pTeleporter, 0);
    expect("a player's GeometryPosition", pPlayerPos, PL);
    expect("a driver's Throttle", qDrvThrottle, 0);
    expect("a target point", qDrvPoint, 0);
    expect("a player's DistanceMoved", pPlayerMoved, PL);
    expect("a player's TheControlMode", pPlayerMode, PL);
    expect("a player's TheMovementMode", pPlayerMove, PL);
    expect("a player's pCarInfo", pPlayerInfo, 0);
    expect("a player's pTopologyCoordinate", pPlayerTopo, 0);
    expect("a player's CarState tail", pPlayerTail, 0);
    expect("a player's CarState hole", pPlayerHole, 0);
    expect("a player's CarIndex", pPlayerIndex, 0);
    expect("the players' slots swapped", pPlayerSlots, PL);
    expect("an AI racer's ForwardSpeed", pRacerSpeed, RC);
    expect("an AI racer's CurrentGear", pRacerGear, RC);
    expect("one racer fewer", pRacersFewer, RC | CP);
    expect("a cop's RPM", pCopRpm, CP);
    expect("a player's RedLineSyncRPM", pPlayerRedLine, 0);
    expect("an AI racer's RedLineSyncRPM", pRacerRedLine, 0);
    expect("a player's ClutchEngaged", pPlayerClutch, PL);
    expect("a cop's RelCoordMatrix", pCopMatrix, CP);
    expect("a player's RelCoordMatrix", pPlayerMatrix, PL);
    expect("a player's MatrixValid", pPlayerValid, PL);
    g_setup = pStale;
    expect("a cop's RelCoordMatrix, not valid", pCopMatrix, 0);
    expect("a player's RelCoordMatrix, not valid", pPlayerMatrix, 0);
    expect("a player's RelCoordMatrix's last lane, not valid",
           pPlayerMatrixEnd, 0);
    expect("a player's MatrixValid, from 0", pPlayerValid, PL);
    expect("a player's BurnOutAllow, the matrix not valid", pPlayerBurnOut,
           PL);
    expect("a player's DistanceMoved, the matrix not valid", pPlayerMovedToo,
           PL);
    g_setup = NULL;
    expect("a traffic car's WheelAngle", pTrafficWheel, TR);
    expect("one traffic car fewer", pTrafficGone, TR);
    expect("a traffic car NULL", pTrafficNull, TR);
    g_setup = pTrafficNull;
    expect("a NULL traffic slot moved", pTrafficNullMoved, TR);
    g_setup = NULL;
    same("AICarPos -1 as 0", pAIBelow, pAIZero);
    same("TrafficCarPos past the cars as at their end", pTrafficPast,
         pTrafficAtEnd);
    expect("the helicopter's TimeUntilThink", pThink, CP);
    expect("the helicopter's Plan", pPlan, CP);
    expect("the helicopter's MoveMode", pMoveMode, CP);
    expect("the helicopter's TargetDistance", pTargetDistance, CP);
    expect("the helicopter's BombRunType", pBombRun, CP);
    expect("the helicopter's CurrentPos", pChopperPos, CP);
    expect("the helicopter's New960", pNew960, CP);
    expect("the helicopter's CurrentCar", pChopperCar, 0);
    expect("the helicopter's ChopperRoute", pChopperRoute, 0);
    expect("the helicopter's padding", pChopperPad, 0);
    expect("no helicopter", pNoChopper, CP);
    expect("the RaceStage", pStage, RA);
    expect("DetectedOneCarRemaining", pOneLeft, RA);
    expect("NumLapsInRace", pLaps, RA);
    expect("ForceRaceFinishPosition", pForcePos, RA);
    expect("ForceRaceFinishPlayerNum", pForcePlayer, RA);
    expect("a RacingCar's CurrentBoundaryRegion", pRegion, RA);
    expect("the last RacingCar's AverageSpeed", pAverage, RA);
    expect("a RacingCar past NumRacingCars", pPastRacing, 0);
    expect("a RacingCar's pCar", pRacingCar, 0);
    expect("one RacingCar fewer", pRacingFewer, RA);
    expect("NumBoundaries", pBoundaries, 0);
    expect("the ghost's file name", pGhost, 0);
    expect("no Race", pNoRace, RA);
    expect("the coordinator's state", pRcState, RA);
    expect("the coordinator's RCExecutingMessage", pRcExec, RA);
    expect("the coordinator's countdown", pRcCount, RA);
    expect("the coordinator's BeforePauseRCState", pRcBefore, RA);
    expect("the coordinator's PausedJoystickPort", pRcPort, 0);
    expect("no coordinator", pNoRc, RA);

    g_what = "the fold";
    build();
    lockhash_world(&g_world, &h);
    for (i = 0; i < LOCKHASH_PARTS; i++) {
        uint16_t was = lockhash_fold(&h);
        int      b;

        for (b = 0; b < 32; b++) {
            h.part[i] ^= 1u << b;
            if (lockhash_fold(&h) == was)
                fault("%s's bit %d did not move it", kLockHashParts[i], b);
            h.part[i] ^= 1u << b;
        }
    }

    g_what = "no World";
    build();
    memset(&h, 0xff, sizeof h);
    lockhash_world(NULL, &h);
    for (i = 0; i < LOCKHASH_PARTS; i++)
        if (h.part[i] != 0) fault("%s %08lx", kLockHashParts[i],
                                  (unsigned long)h.part[i]);
}

// ------------------------------------------------------------ the log

// Not inlined, cloned or left by a tail call, so each draw's return
// address is in here.
__attribute__((noinline, noclone)) static int32_t drawHere(uint32_t* seed,
                                                           int kind)
{
    volatile int32_t r;

    if (kind == 0) r = bRandomI(1000, seed);
    else if (kind == 1) r = (int32_t)(bRandomF(1000.0f, seed));
    else r = bSetRandomSeed(42, seed);
    return r;
}

// An address as the log has it, in drawHere.
static int inDrawHere(uint32_t at)
{
    uint32_t from = (uint32_t)(uintptr_t)(void*)drawHere;

    return at - from <= 256u;
}

#define LINES 400

static char g_lines[LINES][256];
static int  g_numLines;

static void fLog(const char* line)
{
    if (g_numLines < LINES)
        snprintf(g_lines[g_numLines++], sizeof g_lines[0], "%s", line);
}

static int count(const char* prefix)
{
    int i, n = 0;

    for (i = 0; i < g_numLines; i++)
        if (strncmp(g_lines[i], prefix, strlen(prefix)) == 0) n++;
    return n;
}

static const char* find(const char* prefix)
{
    int i;

    for (i = 0; i < g_numLines; i++)
        if (strncmp(g_lines[i], prefix, strlen(prefix)) == 0)
            return g_lines[i];
    return NULL;
}

// Frame n's parts as the log has them: 1 when the line is there and says
// `want`.
static int partsLine(const char* what, uint32_t n, const LockHash* want)
{
    char line[256];

    snprintf(line, sizeof line,
             "lockhash: %s %lu time %08lx seeds %08lx players %08lx racers "
             "%08lx cops %08lx traffic %08lx race %08lx", what,
             (unsigned long)n,
             (unsigned long)want->part[LOCKHASH_TIME],
             (unsigned long)want->part[LOCKHASH_SEEDS],
             (unsigned long)want->part[LOCKHASH_PLAYERS],
             (unsigned long)want->part[LOCKHASH_RACERS],
             (unsigned long)want->part[LOCKHASH_COPS],
             (unsigned long)want->part[LOCKHASH_TRAFFIC],
             (unsigned long)want->part[LOCKHASH_RACE]);
    return find(line) != NULL;
}

// Frame n's world: its timer and seed, so each frame's parts differ.
static void frameWorld(uint32_t n)
{
    WorldTimer   = (int32_t)(1000 + n * 133);
    WorldLoopCounter = (int32_t)(100000 + n);
    // Each frame one car, by its first piece or its last.
    if (n & 1) g_cars[n % 8].State.DistanceMoved = (float)n;
    else g_cars[n % 8].TheControlMode = (ControlMode)n;
    bDefaultSeed = 0x9e3779b9u * (n + 1);
}

// Draws made in frame n, from here: their addresses recorded by the
// harness's own watch.
static int drawsOf(uint32_t n)
{
    return (int)(n % 3 == 0 ? 0 : n % 5 == 0 ? 11 : n % 3);
}

static void logs(void)
{
    LockHash want[160];
    uint32_t n, seed = 77;
    uint16_t fold;
    char     line[64];
    int      i, k;

    g_what = "the log";
    build();
    g_numLines = 0;
    lockhash_differs(5);
    if (g_numLines) fault("logged before start");
    lockhash_start(fLog);
    if (bDefaultSeedWatch == NULL) fault("no watch after start");
    if (bViewSeed == &bDefaultSeed) fault("the view seed bDefaultSeed at GO");
    for (n = 0; n < 160; n++) {
        frameWorld(n);
        for (k = 0; k < drawsOf(n); k++) (void)drawHere(&bDefaultSeed, k & 1);
        (void)bRandomI(7, bViewSeed);   // speech's: not the frame's
        (void)bRandomI(100, &seed);   // another seed: not a draw of its
        frameWorld(n);                // the seed back: the parts as set
        lockhash_world(&g_world, &want[n]);
        fold = lockhash_ran(n, &g_world);
        if (fold != lockhash_fold(&want[n]))
            fault("frame %lu: ran said %04x, the fold %04x", (unsigned long)n,
                  fold, lockhash_fold(&want[n]));
    }
    if (count("lockhash: frame ") != 2)
        fault("%d frame lines, not 2", count("lockhash: frame "));
    if (!partsLine("frame", 0, &want[0])) fault("no frame 0 line as ran");
    if (!partsLine("frame", 150, &want[150]))
        fault("no frame 150 line as ran");
    if (count("lockhash: parts ") || count("lockhash: draws "))
        fault("parts or draws logged before a difference");

    g_numLines = 0;
    lockhash_differs(155);
    if (!find("lockhash: frame 155 differs; the 16 frames up to it"))
        fault("no line for the difference");
    if (count("lockhash: parts ") != LOCKHASH_WINDOW)
        fault("%d parts lines, not %d", count("lockhash: parts "),
              LOCKHASH_WINDOW);
    for (n = 155 - (LOCKHASH_WINDOW - 1); n <= 155; n++) {
        if (!partsLine("parts", n, &want[n]))
            fault("frame %lu: no parts line as ran", (unsigned long)n);
        snprintf(line, sizeof line, "lockhash: draws %lu: %d",
                 (unsigned long)n, drawsOf(n));
        if (!find(line)) fault("no \"%s\"", line);
        snprintf(line, sizeof line, "lockhash: at %lu:", (unsigned long)n);
        k = count(line);
        if (k != (drawsOf(n) + LOCKHASH_LINE - 1) / LOCKHASH_LINE)
            fault("frame %lu: %d lines of draws for %d", (unsigned long)n, k,
                  drawsOf(n));
    }
    // Each address drawHere's: a draw on a line is 9 characters.
    for (i = 0; i < g_numLines; i++) {
        const char* c = strchr(g_lines[i] + 13, ':');
        const char* d;

        if (strncmp(g_lines[i], "lockhash: at ", 13) != 0 || c == NULL)
            continue;
        if (strlen(c + 1) % 9 != 0 || strlen(c + 1) / 9 > LOCKHASH_LINE)
            fault("a draws line \"%s\"", g_lines[i]);
        for (d = c + 1; *d == ' '; d += 9)
            if (!inDrawHere((uint32_t)strtoul(d + 1, NULL, 16))) {
                fault("a draw at %.8s, not in drawHere", d + 1);
                break;
            }
    }
    if (count("lockhash: cars ") != LOCKHASH_WINDOW)
        fault("%d cars lines, not %d", count("lockhash: cars "),
              LOCKHASH_WINDOW);
    for (n = 155 - (LOCKHASH_WINDOW - 1); n <= 155; n++) {
        const char* c;

        snprintf(line, sizeof line, "lockhash: cars %lu timer %08lx loop %08lx:",
                 (unsigned long)n, (unsigned long)want[n].clock[0],
                 (unsigned long)want[n].clock[1]);
        c = find(line);
        if (c == NULL) {
            fault("no \"%s\"", line);
            continue;
        }
        c += strlen(line);
        if (strlen(c) != 9 * LOCKHASH_CARS)
            fault("frame %lu: a cars line of %d characters", (unsigned long)n,
                  (int)strlen(c));
        // Each slot's word moves with its pieces: frame n flipped car
        // n % 8, so only that slot's word differs from frame n - 1's.
        if (n > 155 - (LOCKHASH_WINDOW - 1)) {
            char prev[64];
            const char* d;

            snprintf(prev, sizeof prev, "lockhash: cars %lu ",
                     (unsigned long)(n - 1));
            d = find(prev);
            if (d != NULL) {
                d = strrchr(d, ':') + 1;
                for (k = 0; k < LOCKHASH_CARS; k++) {
                    int moved = strncmp(c + 9 * k, d + 9 * k, 9) != 0;

                    if (moved != (k == (int)(n % 8)))
                        fault("frame %lu: slot %d's word %s", (unsigned long)n,
                              k, moved ? "moved" : "did not move");
                }
            }
        }
    }
    if (count("lockhash: fields ") != 8)
        fault("%d fields lines, not 8", count("lockhash: fields "));
    for (i = 0; i < 8; i++) {
        char want8[256];
        size_t len;

        len = (size_t)snprintf(want8, sizeof want8, "lockhash: fields 155 %d:",
                               i);
        for (k = 0; k < LOCKHASH_FIELDS; k++)
            len += (size_t)snprintf(want8 + len, sizeof want8 - len, " %08lx",
                                    (unsigned long)want[155].car[i][k]);
        if (!find(want8)) fault("no \"%s\"", want8);
    }
    if (count("lockhash: fields 15") != count("lockhash: fields 155 "))
        fault("fields of a frame not the one that differs");

    g_numLines = 0;
    lockhash_differs(158);
    if (g_numLines) fault("a second window in one race");

    // At GO, before a frame has run: none of the last race's.
    lockhash_start(fLog);
    g_numLines = 0;
    lockhash_differs(0);
    if (count("lockhash: parts ") != 0)
        fault("%d parts lines before a frame ran", count("lockhash: parts "));

    // Early in a race: the window from frame 0, to the last frame run.
    lockhash_start(fLog);
    g_numLines = 0;
    for (n = 0; n < 4; n++) (void)lockhash_ran(n, &g_world);
    lockhash_differs(5);
    if (count("lockhash: parts ") != 4)
        fault("%d parts lines for frames 0 to 3", count("lockhash: parts "));
    if (count("lockhash: parts 4 ") || count("lockhash: parts 5 "))
        fault("parts of a frame not run");
    if (count("lockhash: cars ") != 4)
        fault("%d cars lines for frames 0 to 3", count("lockhash: cars "));
    if (count("lockhash: fields "))
        fault("pieces of frame 5, not run");

    // A frame not run whose ring slot has one 64 frames before: no
    // pieces of that one.
    lockhash_start(fLog);
    for (n = 0; n < 70; n++) (void)lockhash_ran(n, &g_world);
    g_numLines = 0;
    lockhash_differs(70);
    if (count("lockhash: parts ") != LOCKHASH_WINDOW - 1)
        fault("%d parts lines for frames 55 to 69", count("lockhash: parts "));
    if (count("lockhash: fields "))
        fault("pieces of frame 6 for frame 70");

    lockhash_stop();
    if (bDefaultSeedWatch != NULL) fault("the watch kept after stop");
    if (bViewSeed != &bDefaultSeed) fault("the view seed kept after stop");
    lockhash_start(fLog);
    lockhash_stop();
    g_numLines = 0;
    lockhash_differs(2);
    if (g_numLines) fault("logged after stop");
}

// ------------------------------------------------------------ the watch

static void*    g_at[8];
static int      g_told;

static void watch(void* at)
{
    if (g_told < 8) g_at[g_told] = at;
    g_told++;
}


static void watchCheck(void)
{
    uint32_t other = 0x12345678u, a, b;
    int32_t  x, y;
    int      kind;

    g_what = "the watch";
    for (kind = 0; kind < 3; kind++) {
        bDefaultSeedWatch = NULL;
        bDefaultSeed = 0x12345678u;
        x = drawHere(&bDefaultSeed, kind);
        a = bDefaultSeed;
        bDefaultSeedWatch = watch;
        bDefaultSeed = 0x12345678u;
        g_told = 0;
        y = drawHere(&bDefaultSeed, kind);
        b = bDefaultSeed;
        if (x != y || a != b) fault("draw %d differs watched", kind);
        if (g_told != 1) fault("draw %d told %d times", kind, g_told);
        else if ((uintptr_t)g_at[0] < (uintptr_t)(void*)drawHere
                 || (uintptr_t)g_at[0] > (uintptr_t)(void*)drawHere + 256)
            fault("draw %d told %p, not in drawHere (%p)", kind, g_at[0],
                  (void*)drawHere);
        g_told = 0;
        (void)drawHere(&other, kind);
        if (g_told) fault("draw %d on another seed told", kind);
    }
    bDefaultSeedWatch = NULL;
}

int main(void)
{
    parts();
    printf("parts: faults %d\n", g_faults);
    pieces();
    printf("pieces: faults %d\n", g_faults);
    logs();
    printf("log: faults %d\n", g_faults);
    watchCheck();
    printf("total faults %d\n", g_faults);
    return 0;
}
