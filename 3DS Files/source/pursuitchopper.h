// pursuitchopper -- the helicopter's side of a chase (12k-7): tPursuit's
// UpdateChopper and IsChopperNearCar, and tCopManager's IsChopperAvailable,
// RequestChopper and Be A Cop's two requests, from retail's copmgr.obj and
// pursuit.obj.
//
// They sit apart from pursuit.c and copmgr.c because they call chopper.c,
// which the cop checkers' harnesses do not link. main.c binds them to the
// seams pursuit.c, playerinput.c, raceinit.c, racecoord.c and worldstep.c
// call through.
//
// Cross-check: tools/pursuitchopper_check.py. Write-up:
// docs/formats/pursuit.md, "The helicopter".

#ifndef PURSUITCHOPPER_H
#define PURSUITCHOPPER_H

#include <stdint.h>

#include "copmanager.h"

struct Car;
struct Chopper;

// The speech manager's (gp-15624): main.c binds speechmgr.h's; NULL says
// nothing.
//   - raiseRotorRequest (0x0020af50): the cop speaker, and whether the
//     supervisor's timer is within 0.001 of 0;
//   - raiseRotorConfirm (0x0020afa0);
//   - raiseDispatchHelicopterNA (0x0020b828): Be A Cop's id.
extern void (*gSpeechRaiseRotorRequestFn)(uint32_t speaker,
                                          int32_t supervisor);
extern void (*gSpeechRaiseRotorConfirmFn)(void);
extern void (*gSpeechRaiseDispatchHelicopterNAFn)(uint32_t speaker);

// tCopManager::IsChopperAvailable, 0x00224ec0. 1 when World has a
// helicopter, the race allows one (RaceParameters' New624), its word at
// 960 is clear and the manager's bChopperBusy is too.
int32_t tcopmanager_is_chopper_available(const tCopManager *m);

// tCopManager::RequestChopper, 0x00224f00. World's helicopter, with
// bChopperBusy set, when the race allows one, none is busy and, in Be A
// Cop, an attack is left. Either way one is taken from
// nBeACopNumChopperAttacks while any are left. NULL otherwise.
struct Chopper *tcopmanager_request_chopper(tCopManager *m);

// tCopManager::BeACopRequestChopper, 0x002287d8. The player cop's chase,
// if it has no helicopter and none is asked for (behaviour 0x20), gets
// behaviours 0x1e0, and "BeACopRequestOk" plays when an attack is left.
// Anything else plays "BeACopRequestFailed".
void tcopmanager_be_a_cop_request_chopper(tCopManager *m);

// tCopManager::BeACopRequestRoadBlock, 0x002288c8. The same for a
// roadblock: no pRoadBlock and behaviour 8 clear give behaviours 0x18,
// and "BeACopRequestOk" when nBeACopNumRoadBlocks is not 0.
void tcopmanager_be_a_cop_request_road_block(tCopManager *m);

// tPursuit::UpdateChopper, 0x00229678, once a step from Update:
//   - a helicopter whose word at 960 is set (egg 5's) is left alone;
//   - with none, behaviour 0x20 and one available, the rotor request,
//     REQUESTED, 10 s, and RequestChopper (its TotalSalvos zeroed); Be A
//     Cop clears 0x20 again;
//   - fChaseDirection -1 outside REQUESTED aborts the bombing run:
//     INFLIGHT, 10 s;
//   - the timer drops by WorldTimeElapsed. Run out, REQUESTED goes
//     INFLIGHT for 5 s with the confirm, or with no helicopter in Be A
//     Cop to NO_CHOPPER with the dispatcher's "not available"; INFLIGHT
//     goes ATTACKING for 15 s and follows the chased car; ATTACKING waits
//     fChopperNextAttackTime, which drops by 2 to at least 6, then
//     attacks, or follows the chased car first if it is on another.
void tpursuit_update_chopper(tPursuit *p);

// tPursuit::IsChopperNearCar, 0x0022bab8. ATTACKING with the helicopter
// under 200 from the chased car in x and y. The speech fillers' (task 29).
int32_t tpursuit_is_chopper_near_car(const tPursuit *p);

// pursuit.c's two seams: the word at 960, and FollowThisCar without its
// result.
int32_t pursuitchopper_new960(struct Chopper *h);
void pursuitchopper_follow_this_car(struct Chopper *h, struct Car *car);

#endif
