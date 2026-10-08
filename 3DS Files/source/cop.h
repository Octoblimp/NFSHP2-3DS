// cop -- the cops themselves: tCop, tPlayerCop and tAICop, retail's
// cop.obj (0x0022d3f8 on).
//
// tCop (copmanager.h) is the base: the pursuit, the car, the cop's number
// and its logic states. tPlayerCop is Be A Cop's, on the player's own car.
// tAICop makes its own car, a CopDriver drives it, and Think moves it
// through the logic states. So far the constructors and destructors, the
// small setters, the zone permissions, DisableMyCar, the drive target,
// tAICop::Think with its transitions, and the limbo, disabled, guard,
// radar-trap, roadblock and patrol logic are ported; DoSnapshot and the
// chases' logic are step 12's later slices (docs/formats/cops.md).

#ifndef COP_H
#define COP_H

#include <stddef.h>
#include <stdint.h>

#include "airoute.h"
#include "bvector.h"
#include "copmanager.h"

struct Car;
struct DriverInfo;

// The image's tables (vtable.h): 8 the destructor, 16 IsAIControlled,
// 24 Think, 32 DoSnapshot. tCop's last three are __pure_virtual.
#define TCOP_VTABLE        0x002bd6e8u
#define TPLAYERCOP_VTABLE  0x002bd6c0u
#define TAICOP_VTABLE      0x002bd698u

// tPlayerCop, retail's 52 bytes, bMalloc'd by CreateCop.
typedef struct tPlayerCop {
    struct tCop Base;                   //  0
    int32_t     nPrevSelection[2];      // 32
    float       fPrevSelectionTimer[2]; // 40
    int32_t     bPrevCopLightState;     // 48
} tPlayerCop;                           // 52

// tAICop, retail's 96 bytes (the demo's .mdebug t1614 is 76), out of
// CopSlotPool. Retail added New32, the two words at 48 and the two at 64.
// New32 is seconds left before a hard hit can disable the car: Think
// counts it down by the frame's time while it is above 0, and teleporting
// the car sets it to 3.
typedef struct tAICop {
    struct tCop  Base;                  //  0
    float        New32;                 // 32 the hit grace timer
    tSpeedTrap  *pMySpeedTrap;          // 36
    int32_t      nMyRoadBlockIndex;     // 40
    float        fSubStateTimer;        // 44
    bVector2     New48;                 // 48 the offset CopDriver's
                                        //    pursuit points take
    bVector2     MyDLOffset;            // 56
    float        New64;                 // 64 6.0 from the constructor
    float        New68;                 // 68 3.0
    float        fFlankSide;            // 72
    NearestRoutePointInfo RouteInfo;    // 76
    float        fSecondsInPhysicsMode; // 84
    float        fMovementModeSwitchDelay; // 88
    int32_t      nDrivingLineIndex;     // 92
} tAICop;                               // 96

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char tplayercop_layout_check[
    (offsetof(tPlayerCop, fPrevSelectionTimer) == 40
     && sizeof(tPlayerCop) == 52) ? 1 : -1];
typedef char taicop_layout_check[
    (offsetof(tAICop, pMySpeedTrap) == 36 && offsetof(tAICop, MyDLOffset) == 56
     && offsetof(tAICop, fFlankSide) == 72 && offsetof(tAICop, RouteInfo) == 76
     && offsetof(tAICop, nDrivingLineIndex) == 92
     && sizeof(tAICop) == 96) ? 1 : -1];
#endif

// tCop::tCop(int), 0x0022d3f8: the number, no pursuit, LS_INVALID, and
// tCop's table. The rest is left as it was. ~tCop, 0x0022d418: bit 0 of
// `flags` frees it (__builtin_delete, bFree).
tCop *tcop_construct(tCop *c, int32_t n);
void  tcop_destruct(tCop *c, int32_t flags);

// SetPursuit (0x0022d530), SetDesiredLogicState (0x0022d538) and
// SetDesiredLogicSubState (0x0022d540): a store each.
void tcop_set_pursuit(tCop *c, tPursuit *p);
void tcop_set_desired_logic_state(tCop *c, eLogicState s);
void tcop_set_desired_logic_sub_state(tCop *c, eLogicSubState s);

// tPlayerCop::tPlayerCop(Car *, int), 0x0022d548, and its destructor,
// 0x0022d5b0. Desired state LS_INVALID, no previous selections.
tPlayerCop *tplayercop_construct(tPlayerCop *c, struct Car *car, int32_t n);
void        tplayercop_destruct(tPlayerCop *c, int32_t flags);

// tAICop::tAICop(DriverInfo *, int), 0x0022db20: makes the cop's car
// ("Car (cop)"), puts it on the world's car list, weighs it for the
// cops' strength, gives it a CopDriver (parked, with the cop's number)
// and no mover, hides it, and asks for LS_LIMBO. pMySpeedTrap and the
// sub-states are left as they were, as retail leaves them.
tAICop *taicop_construct(tAICop *c, struct DriverInfo *info, int32_t n);

// ~tAICop, 0x0022dcc0: tCop's with flags 0, then bit 0 hands the slot
// back to CopSlotPool (operator delete, 0x00230d68).
void taicop_destruct(tAICop *c, int32_t flags);

// operator new (0x00230d78) and delete (0x00230d68): CopSlotPool's.
void *taicop_new(void);
void  taicop_delete(void *p);

// ClearPursuit (0x0022e510): off its pursuit, through
// tPursuit::RemoveCopFromPursuit. ClearSpeedTrap (0x0022e558): its radar
// trap's cop and its own pointer to NULL.
void taicop_clear_pursuit(tAICop *c);
void taicop_clear_speed_trap(tAICop *c);

// DisableMyCar(bool), 0x00230ac8: unless it is in limbo or disabled
// already, wreck the car's damage, let the chased player's radar traps
// wait 10 s longer, leave the pursuit, and ask for LS_DISABLED. The
// argument goes to tPursuit::RemovePrimarySpeaker when the chased player
// is within 75 m. cop_disable_my_car is the same on a tCop, for the
// seam gAICopDisableMyCarFn.
void taicop_disable_my_car(tAICop *c, int32_t b);
void cop_disable_my_car(tCop *c, int32_t b);

// IsNearPursuitTarget, 0x00230bf8: in a pursuit, and within 20 m of the
// chased car.
int32_t taicop_is_near_pursuit_target(const tAICop *c);

// InitializeDriveTarget, 0x00230638: where RouteInfo starts. On patrol
// (asked for, DesiredLogicState), the nearest oncoming traffic route's
// point in LSS_PATROL_ONCOMING (2) when that point is
// within the car's route's width, else the nearest racing route's. In a
// hot pursuit, the chased car's route and point for BLOCK and GET_AHEAD
// and the cop's own for ACQUIRE. Otherwise none.
void taicop_initialize_drive_target(tAICop *c);

// UpdateDriveTarget, 0x002307d0: rebuilds the car driver's target as the
// 20 route points on from RouteInfo, at MyDLOffset (and the driving line's
// offset, with one). Unless `keep` is set, RouteInfo first steps on past
// `pos` (at most ten points; ten exactly starts it again once from
// InitializeDriveTarget), and the target's first point becomes `pos`.
void taicop_update_drive_target(tAICop *c, const bVector2 *pos,
                                int32_t keep);

// tAICop::Think, 0x0022df88, table slot 24, once a frame from the cop
// manager's Think. In order: New32 counts down while above 0; the camera's
// car shows its driver's target; MovementModeTransitions; a car on its
// side or roof (BodyMatrix.v2.z at most 0.1) below 10 mph is disabled
// (DisableMyCar(1)), and so is one with a tire blown (DisableMyCar(0));
// fSubStateTimer counts down to 0; a new DesiredLogicState goes through
// HandleStateTransitions; the state's logic runs; and New48 eases toward
// MyDLOffset, x at New64 and y at New68 a second, both set again to 6
// and 3.
void taicop_think(tAICop *c);

// HandleStateTransitions(from, to), 0x0022e1f0. fSubStateTimer goes to 0.
// Leaving DISABLED resets the car's damage (tCopManager::ResetAllDamage);
// leaving LIMBO turns its collisions and rendering back on, puts it in
// COP_MOVEMENT and resets its damage; leaving SPEED_TRAP lets the trap go.
// Entering:
//   LIMBO        off its pursuit, hidden from the map, siren and lights
//                off, no movement, the driver parked, collisions off, not
//                rendered; LIMBO_DISABLED with a 1 s timer from DISABLED,
//                else LIMBO_READY.
//   DISABLED     off its trap and pursuit, the driver disabled, siren
//                broken, lights 1, MELLOW_MOVEMENT, and the car's driver
//                braking (0.3, the e-brake full on) for 0 over 10 s.
//   SPEED_TRAP   damage reset, then InitSpeedTrapLogic.
//   ROAD_BLOCK   damage reset, then InitRoadBlockLogic.
//   PATROL       off its pursuit, the drive target from the car's place,
//                the driver patrolling, lights and siren off.
//   HOT_PURSUIT  lights 2, siren 1, on the map, the driver pursuing, sub-
//                state NONE asking for PURSUIT_FOLLOW.
//   CAUGHT_SPEEDER  no pursuit, the driver parked, CAUGHTSPEEDER_TICKETING,
//                lights 1, on the map, siren off.
//   GUARD        off its trap and pursuit, damage reset, the driver parked,
//                lights, map and siren off, sub-state NONE.
void taicop_handle_state_transitions(tAICop *c, eLogicState from,
                                     eLogicState to);

// MovementModeTransitions, 0x0022e578: between the cheap COP_MOVEMENT and
// the real simulation. Nothing with no movement or DISABLED asked for. Off
// COP_MOVEMENT fSecondsInPhysicsMode counts up (below 0, or NaN, nothing
// more happens), and a car with all four wheels down, not skidding (velocity more than 10
// degrees off its heading above 17.88 m/s) and turning at no more than
// 1 rad/s goes back to COP_MOVEMENT after 0.1 s more of that. In
// COP_MOVEMENT, a car its CopMover has airborne goes to MELLOW_MOVEMENT,
// its upward speed held to 2 m/s and its matrix out of date, with the
// driver at full throttle keeping its forward speed.
void taicop_movement_mode_transitions(tAICop *c);

// Retail's 0x00230a60, with no demo twin: the car's driver's drive target
// cleared and set to the car's own place. DoLimboLogic (0x00230570) holds
// position and moves LIMBO_DISABLED on to LIMBO_READY once its timer is
// out. DoDisabledLogic (0x002305c8) holds position and asks for LIMBO once
// no player is within 250 m. DoGuardLocationLogic (0x00230bf0) holds
// position.
void taicop_hold_position(tAICop *c);
void taicop_do_limbo_logic(tAICop *c);
void taicop_do_disabled_logic(tAICop *c);
void taicop_do_guard_location_logic(tAICop *c);

// Teleport(bVector2 *, unsigned short), 0x0022de70: a cop with a car puts
// it in COP_MOVEMENT and resets it, stopped, to (x, y, 0) facing `ang`.
// SetSpeedTrap (0x0022ded8): the trap and its cop each other's, the car
// teleported to the trap, and LS_SPEED_TRAP asked for. SetRoadBlock
// (0x0022df18): on pursuit `p`, at roadblock spot `i`, the car teleported
// there, and LS_ROAD_BLOCK asked for.
void taicop_teleport(tAICop *c, const bVector2 *pos, uint16_t ang);
void taicop_set_speed_trap(tAICop *c, tSpeedTrap *t);
void taicop_set_road_block(tAICop *c, tRoadBlock *rb, tPursuit *p,
                           int32_t i);

// IsValidPursuitTarget(Car *, bool), 0x0022ea88: not the player cop's car,
// not pulled over, its fPursuableTimer not above 0; then yes if it caused
// a collision just now (CarCausedRecentCollision), else, with `b` set, if
// it goes faster than 80 mph either way or a pursuit has it already.
// CanPatrollerSeeThisCar(Car *), 0x0022ed68: within 50 m of the cop's car,
// moving, and at least 20 m on along its own heading from it -- going
// away ahead of the cop.
int32_t taicop_is_valid_pursuit_target(tAICop *c, struct Car *car,
                                       int32_t b);
int32_t taicop_can_patroller_see_this_car(const tAICop *c,
                                          const struct Car *car);

// The radar trap's, the roadblock's and the patrol's logic.
//   InitSpeedTrapLogic (0x0022e798): off its pursuit, then parked -- sub-
//     state NONE, off the map, stopped, the driver PARKED, the matrix out
//     of date, lights and siren off -- with 15 s before it may give up.
//   InitRoadBlockLogic (0x0022ebc0): the same parking with lights 1, its
//     pursuit and timer untouched.
//   DoSpeedTrapLogic (0x0022e838): holds position. Once the timer is out,
//     no player within 250 m asks for LS_LIMBO and ends it. A car more
//     than 1 cm or 100 BAM off its trap goes back to it if CanTeleport
//     says so. Then each racer and player within 45 m in x and y and
//     2.5 m in z that IsValidPursuitTarget (fast enough or chased) and
//     the manager's RequestPursuit allow asks for LS_HOT_PURSUIT.
//   DoRoadBlockLogic (0x0022ec38): holds position; a car off its spot of
//     its pursuit's roadblock goes back the same way; New32 to 3 s.
//   DoDrivingOnPatrolLogic (0x0022ee50): no offsets; the drive target on
//     from the car's place; LS_LIMBO with no player within 250 m; else
//     the trap's search, with the fast-or-chased test only for a car
//     CanPatrollerSeeThisCar.
void taicop_init_speed_trap_logic(tAICop *c);
void taicop_init_road_block_logic(tAICop *c);
void taicop_do_speed_trap_logic(tAICop *c);
void taicop_do_road_block_logic(tAICop *c);
void taicop_do_driving_on_patrol_logic(tAICop *c);

// The rest of the logic, not ported yet: NULL seams that do nothing, so a
// cop asked for one of these states sits in it. DoHotPursuitLogic
// (0x0022ff58) and DoCaughtSpeederLogic (0x002303c8), 12g-3; and
// tPlayerCop::Think (0x0022d5c8), Be A Cop's, 12m.
extern void (*gAICopDoHotPursuitLogicFn)(tAICop *c);
extern void (*gAICopDoCaughtSpeederLogicFn)(tAICop *c);
extern void (*gPlayerCopThinkFn)(tPlayerCop *c);

// The cops' cooperation zones. InitZonePermissionTable (0x0022f770)
// fills nZonePermissionTable[6][6] (0x0031c5c8), which
// RequestZonePermission(a, b) (0x0022f810) reads as [b][a], with zone 6
// always allowed. GetZoneFromSubState (0x0022f850): the zone a pursuit
// sub-state works in, by which side `side` says (below 0 one way).
extern int32_t nZonePermissionTable[36];
void    init_zone_permission_table(void);
int32_t request_zone_permission(int32_t a, int32_t b);
int32_t get_zone_from_sub_state(eLogicSubState s, float side);

// fCopMassTable (0x0031c5b8): an AI cop car's mass by
// tCopManager::nDifficultyLevel, the inertia scaled to match.
extern float fCopMassTable[3];

// Not ported yet, NULL until they are. Each aborts where retail would
// call it: tPursuit::RemoveCopFromPursuit (0x0022c740) and
// RemovePrimarySpeaker (0x0022c990), and CarDamage's wreck-everything
// (0x001b5bc8: all 32 parts by 1.0, then RethinkDamage), which no port
// car reaches while gCarDamageCtorFn is NULL.
extern void (*gPursuitRemoveCopFromPursuitFn)(tPursuit *p, tCop *c);
extern void (*gPursuitRemovePrimarySpeakerFn)(tPursuit *p, int32_t b);
extern void (*gCarDamageWreckFn)(void *damage);

// tCopManager::RequestPursuit(tCop *, Car *), 0x00225078, 12h: nonzero
// when the cop may chase the car. NULL grants none, so no patrol or radar
// trap starts a chase yet.
extern int32_t (*gCopManagerRequestPursuitFn)(tCopManager *m, tCop *c,
                                              struct Car *car);

// The three tables, for main.c.
void cop_install_vtables(void);

#endif
