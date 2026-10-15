// lockhash -- the world's checksum in parts, for a wireless race run in
// lockstep (TASKS 37e). The port's.
//
// netstep (netstep.h) has each console say its checksum of the world after
// every frame, and say in the log when another console's differs. That
// tells that the race went two ways, not where. Here the checksum is the
// fold of seven parts, each a hash of its own state after the frame:
//
//   time     WorldTimer, the world's pause and time scale, and retail's own
//            debug checksum (each car's x + y; it also fills
//            CarPositionTable, as it did for 37d)
//   seeds    bDefaultSeed and the World's own seed
//   players  each player's car's CarState, from GeometryPosition to
//            DistanceMoved: no pointer, every float as its bits
//   racers   the AI racers' cars, the same
//   cops     the cops' cars, the same, and the helicopter's plan, move,
//            salvos, position, matrix and speed
//   traffic  the traffic's cars, the same
//   race     the Race's stage, clocks and counts, each RacingCar's laps,
//            positions, times and finish (all but its pointer), and the
//            coordinator's state
//
// Each console keeps its parts for the last NETSTEP_RING frames, and the
// draws on bDefaultSeed by frame with the address that drew (bmath.h's
// bDefaultSeedWatch). Told that a frame differs, it logs the parts and the
// draws of the LOCKHASH_WINDOW frames up to it, once a race, so the two
// consoles' logs show which part went first and what drew. With them go
// the clocks and a hash of each slot's car, and at the frame itself each
// car in pieces (LOCKHASH_FIELDS), so the logs show which car went and in
// what. Every NETSTEP_LOG_EVERY frames it logs the parts too, as netstep
// its checksum.
//
// From GO to the race's end it also points bmath.h's bViewSeed at a seed of
// its own. Each console runs every player's logic as retail ran its two
// players, cameras and all, so a draw from what is shown or heard is the
// same on each -- all but cop speech, which waits for the console's own
// audio to be quiet (copmanager_time_based_speech): a console whose sound
// plays a line longer, or not at all, would draw the next speech's gap and
// filler at another frame and move bDefaultSeed for the world. On the view
// seed, speech, cameras and models' start times draw what they like.
//
// Host-buildable: tools/src/lockhash_test.c builds the World, cars, race
// and coordinator itself.

#ifndef LOCKHASH_H
#define LOCKHASH_H

#include <stdint.h>

#include "netstep.h"

struct World;

enum {
    LOCKHASH_TIME,
    LOCKHASH_SEEDS,
    LOCKHASH_PLAYERS,
    LOCKHASH_RACERS,
    LOCKHASH_COPS,
    LOCKHASH_TRAFFIC,
    LOCKHASH_RACE,
    LOCKHASH_PARTS
};

#define LOCKHASH_WINDOW 16     // frames logged up to the one that differs
#define LOCKHASH_DRAWS  1024   // draws kept, a power of two
#define LOCKHASH_LINE   8      // draws on a line of the log
#define LOCKHASH_CARS   14     // the World's slots, WORLD_MAX_CARS

// A car in pieces, for the window: its control and movement modes, then
// its CarState from GeometryPosition to DistanceMoved in eight spans, and
// its driver. The driver is in no part: what it holds goes into the
// CarState on the frame it drives, so a part would only say it sooner.
// The window's line of cars does, as each slot's word folds every piece:
// the frame the driver first went is the first where the word differs
// (Session 109, the post-finish split with every CarState piece of slot
// 0 differing at once).
enum {
    LOCKHASH_MODES,     // TheControlMode, TheMovementMode
    LOCKHASH_PLACE,     // GeometryPosition, Position
    LOCKHASH_MOTION,    // Velocity, Acceleration
    LOCKHASH_BODY,      // BodyMatrix
    LOCKHASH_SPIN,      // AngularVelocity, AngularAcceleration
    LOCKHASH_WHEELMATS, // WheelMatrix, BrakeMatrix
    LOCKHASH_WHEELS,    // WheelAngularVelocity to WheelTractionUsage
    LOCKHASH_DRIVE,     // Angle to BurnOutAllow: steering, gear, throttle
    LOCKHASH_REL,       // RelCoordMatrix to DistanceMoved
    LOCKHASH_DRIVER,    // the CarDriver's inputs and its target's points
    LOCKHASH_FIELDS
};

typedef struct LockHash {
    uint32_t part[LOCKHASH_PARTS];
    // Not in the fold, only for the window: WorldTimer and
    // WorldLoopCounter as the frame left them, and each slot's car in
    // pieces (0 for a NULL slot or one past TotalNumCars).
    uint32_t clock[2];
    uint32_t car[LOCKHASH_CARS][LOCKHASH_FIELDS];
} LockHash;

typedef void (*LockHashLogFn)(const char* line);

// The parts' names in the log, in order.
extern const char* const kLockHashParts[LOCKHASH_PARTS];

// The parts of `w` (NULL: every part 0) and the race and coordinator up.
void lockhash_world(struct World* w, LockHash* h);

// The parts to netstep's checksum.
uint16_t lockhash_fold(const LockHash* h);

// GO: the ring cleared, the draws watched from here on, nothing logged
// yet, and bViewSeed on a seed of its own, from bDefaultSeed's. Stop: the
// draws no longer watched, and bViewSeed back on bDefaultSeed.
void lockhash_start(LockHashLogFn log);
void lockhash_stop(void);

// Frame `n` ran: its parts kept (and logged every NETSTEP_LOG_EVERY), and
// what draws next is frame n + 1's. The checksum for netstep_done.
uint16_t lockhash_ran(uint32_t n, struct World* w);

// Frame `n` differs from another console's: the window's parts, draws,
// clocks and cars (a hash of each slot), once a race, and frame n's cars
// in pieces.
void lockhash_differs(uint32_t n);

// The names of a car's pieces in the log, in order.
extern const char* const kLockHashFields[LOCKHASH_FIELDS];

#endif
