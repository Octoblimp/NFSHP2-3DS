// rcauto -- RaceCoordinator.obj from retail: the auto replay.
//
//   RaceCoordinator::RCStateAutoReplayCallback  0x0014b848  1176 bytes
//   RaceCoordinator::SetUpAutoReplay            0x0014c0f8    80 bytes
//   RaceCoordinator::CleanUpAutoReplay          0x0014c148   168 bytes
//   RaceCoordinator::CheckAutoReplayCam         0x0014c1f0   232 bytes
//   RaceCoordinator::SetUpAutoReplayCam         0x0014c2d8   952 bytes
//
// TASKS 72g-4, for completeness. The auto replay would show an incident
// again three times, on a camera flown along the road beside it, with the
// letterbox bars up. Retail never enters it: nothing calls SetUpAutoReplay
// or posts RC_REQUEST_AUTO_REPLAY (7), and nothing takes the
// AUTO_REPLAY_SNAPSHOT its ACTIVATE restores. docs/formats/replay.md has the
// decode.

#ifndef RCAUTO_H
#define RCAUTO_H

#include <stdint.h>

#include "racecoord.h"

struct Car;

// The snapshots the state takes, restores and deletes by name.
#define RC_AUTO_THE_PRESENT     "THE_PRESENT"
#define RC_AUTO_SNAPSHOT        "AUTO_REPLAY_SNAPSHOT"
#define RC_AUTO_INSTANT_REPLAY  "INSTANT_REPLAY"

// What the allocations are named, and their sizes and lines on the disc.
// The sizes are the 3DS's (trackcarcam.h and previewroute.h assert them);
// a 64-bit host's records are larger.
#define RC_AUTO_FILE            "..\\indep\\src\\racecoordinator.cpp"
#define RC_AUTO_MOVER_NAME      "TrackCarCameraMover"
#define RC_AUTO_ROUTE_SIZE      24
#define RC_AUTO_CD_SIZE         164
#define RC_AUTO_MOVER_SIZE      1136
#define RC_AUTO_FOV_ENTRIES     32

// AUTO_REPLAY.
//
// ACTIVATE takes THE_PRESENT, keeps the highlight car's place as the
// final position, restores AUTO_REPLAY_SNAPSHOT and then INSTANT_REPLAY,
// and keeps the car's place there as the start. CheckAutoReplayCam (on
// pRaceCoordinator, as retail has it) then asks for a route between the
// two. Any of these failing changes back to RACE_IN_PROGRESS. Otherwise
// the letterbox bars (0x49c15518) show, the rewinds are 0, every player's
// camera movers go off and SetUpAutoReplayCam makes the camera.
//
// TICK waits for the replay to reach the capture's end. Then a rewind: the
// first restores INSTANT_REPLAY and flies the camera along the road's left
// edge, following the second highlight car, the look pushed the other way;
// the second restores AUTO_REPLAY_SNAPSHOT and flies it along the route's
// line, with no push; the third sends RC_SKIP.
//
// UNACTIVATE restores and deletes THE_PRESENT, hides the bars, cleans up,
// turns the camera movers back on and puts the joystick's type-changed
// handlers back. RC_SKIP changes to RACE_IN_PROGRESS. TAKE_AUTOSNAPSHOT is
// taken. Every other message answers 0.
int32_t rc_state_auto_replay_callback(RaceCoordinator *rc, RCMessage msg,
                                      int32_t param);

// 0x0014c0f8. The two highlight cars and the view, the first car's route
// point (Car::GetRoutePoint with 1) as the incident point and its place as
// the incident's.
void racecoordinator_set_up_auto_replay(RaceCoordinator *rc,
                                        struct Car *car, struct Car *car2,
                                        int32_t viewID);

// 0x0014c148. The camera mover deleted, the camera data, the FOV table,
// the route, the bank and the eye points freed, each pointer NULL after.
// racecoord.h's gRCCleanUpAutoReplayFn, which the destructor calls.
void racecoordinator_clean_up_auto_replay(RaceCoordinator *rc);

// 0x0014c1f0. Cleans up, then a PreviewRoute from the highlight car, 100
// out and as long as the track runs from the start to the final position.
// 1 when it has 5 points or more; else cleaned up again, and 0.
int32_t racecoordinator_check_auto_replay_cam(RaceCoordinator *rc);

// 0x0014c2d8. The camera data, the FOV table (32 entries at 40 degrees)
// and an eye point 5 above the road's right edge at each of the route's
// points, banked flat; the percentages from the start to the final
// position the race's way; and a TrackCarCameraMover on the view following
// the highlight car. Retail leaves the record's area fields, its
// EnterHorizComp and its ShakeBankNumber as bMalloc gives them.
void racecoordinator_set_up_auto_replay_cam(RaceCoordinator *rc);

#endif
