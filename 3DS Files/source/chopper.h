// chopper -- Chopper.obj, the police helicopter (retail 0x001e7a90 ..
// 0x001eae04), and the bombing runs' table.
//
// Chopper is task 26's, and 12k ports it in slices. The demo's is 752
// bytes (.mdebug type#2444); retail's is 976:
//   - its TopologyCoordinate is 704 bytes where the demo's was 560, so
//     everything after it is 144 further on;
//   - two words follow Timeout (824 and 828, the port's names below);
//   - a matrix sits at 848, built by CalcMatrix (0x001ea3f8), where the
//     demo's GetMatrix built one on each call;
//   - and a word follows EmitDust (960), set by the constructor when Easter
//     egg 5 is on.
//
// 12k-2 has the object: the constructor and destructor, ClearVariables,
// following and attacking a car, finding the bombing run's target spot,
// and placing the helicopter in the world and taking it out. 12k-3a has
// the chase logic under the planning: arriving and leaving, following a
// route, staking out a signpost, hanging about near a point and keeping
// the target over the sheet. 12k-3b has the plans over them:
// HighLevelPlanning, CleverPursuitPlan and BombRunLogic. 12k-4a has the
// flying under them, Think, and 12k-4b Fly, the moving and the dust.
// 12k-7 has the chase's side, tPursuit's UpdateChopper and the manager's
// requests, in pursuitchopper.c. 12k-6 has the salvos: FireSalvo in
// chopperfire.c, and the rockets, smoke bombs and spikes it launches in
// munition.c, smokeables of their own.
//
// The ChopperSound is 14-7's, in choppersound.c; main.c sets
// gCreateChopperSoundFn to choppersound_create. Without it the port
// builds none and skips every call through it; retail calls through it
// unguarded except in the destructor.
//
// Cross-check: tools/chopper_check.py. Write-up: docs/formats/chopper.md.

#ifndef CHOPPER_H
#define CHOPPER_H

#include <stddef.h>
#include <stdint.h>

#include "airoute.h"
#include "blist.h"
#include "bmatrix.h"
#include "bvector.h"
#include "sound3d.h"
#include "topology.h"
#include "trackpath.h"
#include "trackroute.h"
#include "worldobject.h"

struct Car;

// ChopperPlan, .mdebug t5264.
typedef int32_t ChopperPlan;
#define CHOPPLAN_PURSUIT          ((ChopperPlan)0)
#define CHOPPLAN_HEAD_TO_STAKEOUT ((ChopperPlan)1)
#define CHOPPLAN_AT_STAKEOUT      ((ChopperPlan)2)
#define CHOPPLAN_START_CHASE      ((ChopperPlan)3)
#define CHOPPLAN_BOMBING_RUN      ((ChopperPlan)4)
#define CHOPPLAN_END_CHASE        ((ChopperPlan)5)
#define CHOPPLAN_EATING_DONUTS    ((ChopperPlan)6)

// ChopperMoveMode, .mdebug t1451.
typedef int32_t ChopperMoveMode;
#define CHOPMOVE_PURSUIT          ((ChopperMoveMode)0)
#define CHOPMOVE_ROTATE           ((ChopperMoveMode)1)

// ChopperAttackType, .mdebug t5266. The demo has four. Retail's table has
// a fifth row, which the port names by its number.
typedef int32_t ChopperAttackType;
#define CHOPATTACK_ROCKET         ((ChopperAttackType)0)
#define CHOPATTACK_SMOKE_BOMB_1   ((ChopperAttackType)1)
#define CHOPATTACK_SMOKE_BOMB_2   ((ChopperAttackType)2)
#define CHOPATTACK_SPIKE_BELT     ((ChopperAttackType)3)
#define CHOPATTACK_4              ((ChopperAttackType)4)
#define CHOPATTACK_NUM            5

// MunitionType, .mdebug t3606.
typedef int32_t MunitionType;
#define CM_ROCKET                 ((MunitionType)0)
#define CM_SMOKEBOMB              ((MunitionType)1)
#define CM_DROPPED_SPIKES         ((MunitionType)2)

// BombRunBehaviour, 32 bytes (.mdebug type#3607): one row a ChopperAttack-
// Type, indexed unchecked.
typedef struct BombRunBehaviour {
    MunitionType Type;          //  0
    float        Ahead;         //  4  seconds of the car's speed
    float        Velocity;      //  8
    float        Adjust;        // 12
    int32_t      SalvoSize;     // 16
    int32_t      NumSalvos;     // 20
    float        SalvoSpread;   // 24
    float        SalvoDelay;    // 28
} BombRunBehaviour;

typedef char bombrunbehaviour_size_check[
    sizeof(BombRunBehaviour) == 32 ? 1 : -1];

// Retail's table, 0x0031a7c8.
extern const BombRunBehaviour BombRunBehaviours[CHOPATTACK_NUM];

struct Chopper {
    Sound3d            *pChopperSound;      //   0  ChopperSound *
    WorldObject        *WorldObj;           //   4  "TRACK_HELICOPTER"
    TopologyCoordinate  TopologyCoord;      //   8
    bNode               DustEmitters;       // 712  bTList<AcidEmitter>
    float               TimeUntilThink;     // 720
    struct Car         *CurrentCar;         // 724
    ChopperPlan         Plan;               // 728
    ChopperMoveMode     MoveMode;           // 732
    TrackRoute         *ChopperRoute;       // 736
    TrackRoutePoint    *ChopperPoint;       // 740
    TrackRoute         *TargetRoute;        // 744
    TrackRoutePoint    *TargetPoint;        // 748
    TrackPathCoordinate TP;                 // 752
    float               TargetDistance;     // 792
    TrackRoute         *OldCarRoute;        // 796
    TrackRoutePoint    *OldCarPoint;        // 800
    ChopperAttackType   BombRunType;        // 804
    int32_t             NumSalvosReleased;  // 808
    float               TimeUntilNextSalvo; // 812
    int32_t             NextLauncher;       // 816
    float               Timeout;            // 820
    float               StuckTime;          // 824  retail's
    int32_t             TotalSalvos;        // 828  retail's
    bVector3            CurrentPos;         // 832
    bMatrix4            Matrix;             // 848  retail's
    float               Speed;              // 912
    bVector2            Acceleration;       // 916
    float               Roll;               // 924
    float               DesiredRoll;        // 928
    float               Yaw;                // 932
    float               Pitch;              // 936
    float               DesiredPitch;       // 940
    float               RotRate;            // 944
    float               ZVelocity;          // 948
    float               GroundZ;            // 952
    int32_t             EmitDust;           // 956  bool
    int32_t             New960;             // 960  retail's: egg 5
    uint8_t             _pad964[12];        // 964
};                                          // 976

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char chopper_layout_check[
    (offsetof(struct Chopper, TopologyCoord) == 8
     && offsetof(struct Chopper, DustEmitters) == 712
     && offsetof(struct Chopper, Plan) == 728
     && offsetof(struct Chopper, TP) == 752
     && offsetof(struct Chopper, TargetDistance) == 792
     && offsetof(struct Chopper, Timeout) == 820
     && offsetof(struct Chopper, TotalSalvos) == 828
     && offsetof(struct Chopper, CurrentPos) == 832
     && offsetof(struct Chopper, Matrix) == 848
     && offsetof(struct Chopper, Speed) == 912
     && offsetof(struct Chopper, Roll) == 924
     && offsetof(struct Chopper, GroundZ) == 952
     && offsetof(struct Chopper, New960) == 960
     && sizeof(struct Chopper) == 976) ? 1 : -1];
#endif

// ChopperTarget, 12 bytes: where the planning sends the helicopter, and
// how fast. HighLevelPlanning (0x001e9648) fills one for Think.
typedef struct ChopperTarget {
    bVector2 Location;          // 0
    float    DesiredSpeed;      // 8
} ChopperTarget;

typedef char choppertarget_size_check[
    sizeof(ChopperTarget) == 12 ? 1 : -1];

// ChopperSound's table. Its first base is Sound3d, so the vptr is the
// Sound3d's at +28.
#define CHOPPERSOUND_VTABLE       0x002bc2a8u
#define CHOPPERSOUND_VT_DTOR      8     // (this, flags)
#define CHOPPERSOUND_VT_ACTIVATE  16    // (this, bool)
#define CHOPPERSOUND_VT_UPDATE    24    // (this, float, uint16, float)
#define CHOPPERSOUND_VT_MUTE      32    // (this, int)

// sound::CreateChopperSound(Chopper *), 0x00215098. NULL (the default)
// builds none.
extern Sound3d *(*gCreateChopperSoundFn)(struct Chopper *h);

// The timeout ClearVariables and AttackCar set, 0x41c80000.
#define CHOPPER_TIMEOUT 25.0f

// -------------------------------------------------------------- the object

// Chopper::Chopper(), 0x001e7a90, in place on `mem`, which it returns:
//   - the TopologyCoordinate, the dust list (empty) and the TP;
//   - WorldObj, a WorldObject from WorldObjectSlotPool named
//     "TRACK_HELICOPTER", with no matrix and lighting;
//   - pChopperSound, from gCreateChopperSoundFn;
//   - the dust emitters, afxGetEmitters of "XEM_HELI_DUST";
//   - ClearVariables, then Plan EATING_DONUTS;
//   - New960 1 when neither AIDemoMode nor ReplayDemoMode is set and egg 5
//     is on (raceinit.h's gEggIsOnFn).
struct Chopper *chopper_construct(void *mem);

// Chopper::~Chopper(), 0x001e7b80: the dust emitters deleted; the sound
// and WorldObj, each when set, through their destructors with 3; and with
// bit 0 of `flags` the block back to the heap (bFree).
void chopper_destruct(struct Chopper *h, int32_t flags);

// 0x001e7c38. Every field after the TP back to its start: zeroes, except
// Matrix (the identity) and Timeout (25). The TP is reset at CurrentPos,
// which is zero by then.
void chopper_clear_variables(struct Chopper *h);

// 0x001e7f80. With New960 set, the car becomes the player's (World's
// CarTable[0]) whatever it was, NULL included. 0 with no HeliSheet or no
// signposts. With no car: from START_CHASE or EATING_DONUTS, CurrentCar
// NULL and EATING_DONUTS; otherwise END_CHASE. With a car: only from
// EATING_DONUTS or START_CHASE, CurrentCar it and START_CHASE; otherwise
// 0. Each change also zeroes TimeUntilThink and returns 1.
int32_t chopper_follow_this_car(struct Chopper *h, struct Car *car);

// 0x001e8040. Only in PURSUIT: a BOMBING_RUN of that type starts, from the
// distance to the car (negative when the helicopter is behind it), at the
// helicopter's own point, with the car's route and point remembered. Then
// AdjustBombTarget, and 1. Otherwise FollowThisCar(CurrentCar) when there
// is one, and 0.
int32_t chopper_attack_car(struct Chopper *h, ChopperAttackType type);

// 0x001e8140. The run's lead is Ahead seconds of the car's speed, at least
// 100. A target nearer than that less 24 is shifted to it, then moved on
// to open ground.
void chopper_adjust_bomb_target(struct Chopper *h);

// 0x001e81d8. TargetDistance becomes `dist`. Of up to five points
// `dist + 24` on along the car's route, the first not marked
// TRP_NO_HELISHEET becomes the target; with none, the target stays.
void chopper_shift_target(struct Chopper *h, float dist);

// 0x001e82c0. From the target on, point by point, while the HeliSheet's
// polygon under the point has flag bit 0; each step adds the point's
// Length to TargetDistance.
void chopper_find_unobstructed_spot(struct Chopper *h);

// 0x001e8358. GroundZ, the ground's height under (CurrentPos.x,
// CurrentPos.y, GroundZ); returns its terrain type.
int32_t chopper_find_ground_height(struct Chopper *h);

// 0x001e83b0. Sound on; CurrentPos (pos, z); Yaw the car's heading in
// degrees; Pitch, Roll, their targets and Speed zero; the TP reset there;
// the interest box 1 round it; GroundZ from the car's height, then the
// ground's; the helicopter's route point found afresh; the matrix built.
void chopper_place_in_world(struct Chopper *h, const bVector2 *pos, float z);

// 0x001e84a8. WorldObj disabled, the sound off, the interest box cleared.
void chopper_remove_from_world(struct Chopper *h);

// 0x001e84f0. 1 when the TP's distance round the track is at or behind the
// car's (TrackPathManager::CompareDistances <= 0).
int32_t chopper_behind_car(struct Chopper *h);

// 0x001e8540. `v` turned by 360 - Yaw degrees into `out`.
void chopper_rotate_to_chopper_coord(struct Chopper *h, bVector2 *out,
                                     const bVector2 *v);

// 0x001e8560. -120 heading to or at a stakeout, else -60.
float chopper_get_max_deceleration(const struct Chopper *h);

// 0x001eadf0. A BOMBING_RUN becomes PURSUIT.
void chopper_abort_bombing_run(struct Chopper *h);

// 0x001ead80 / 0x001eadb0. The sound's Mute(i), and its Update(1, 0, 1).
void chopper_mute(struct Chopper *h, int32_t i);
void chopper_update_sound(struct Chopper *h);

// 0x001e8798. The nearest route point to CurrentPos over the racing
// routes (GetNearestRoutePoint, flags 6); when found, ChopperRoute and
// Point.
void chopper_find_point_from_scratch(struct Chopper *h);

// 0x001e87e8. ChopperRoute's closest point within 24, flags 6. Failing
// that, when ChopperPoint has a signpost, the sign's new route's. Failing
// both, FindChopperPointFromScratch.
void chopper_find_route_point(struct Chopper *h);

// 0x001ea3f8. Matrix: a scale of 1.1 (gp-27984) on x, y and z, turned by
// Roll on x, 360 - Pitch on y and 180 - Yaw (plus 360 below 0) on z, each
// in BAM (degrees * 65536 truncated, then / 360), with CurrentPos raised
// by 2.3 (gp-27980) as its translation.
void chopper_calc_matrix(struct Chopper *h);

// 0x001ea578. Matrix to WorldObj's, and WorldObj enabled.
void chopper_update_world_object(struct Chopper *h);

// -------------------------------------------------------- the chase logic

// 0x001e8590. HighLevelPlanning's START_CHASE: `on_sheet`, `flags` and
// `z` are the HeliSheet's answer (FindZValue) at the target. Off the
// sheet, or on a polygon with flag bit 1, 1: wait. Otherwise the
// helicopter is placed 150 over the sheet there and drops at 25 (ZVelocity
// -25), in PURSUIT, raising dust unless the polygon has flag bit 0; 0.
int32_t chopper_start_chase_logic(struct Chopper *h, ChopperTarget *t,
                                  int32_t on_sheet, uint32_t flags, float z);

// 0x001e8608. END_CHASE, from the sheet under CurrentPos:
//   - 150 or more over it: out of the world, EATING_DONUTS, and 1;
//   - over a polygon with flag bit 1 while not climbing (ZVelocity 0),
//     or off the sheet: at 50 for the first point on from ChopperPoint
//     (GetNextRoutePoint) more than 30 from the helicopter, or the last
//     before the route runs out; 0;
//   - otherwise climbing at 25, the target where it is; 0.
int32_t chopper_end_chase_logic(struct Chopper *h, ChopperTarget *t);

// 0x001e88c0. The car's speed (VelocityMagnitude) plus 30.
void chopper_set_follow_speed(struct Chopper *h, ChopperTarget *t);

// 0x001e88e0. Back from `info` against `b` (FindNearbySignpost with
// !b) to the fork it came off: `info` becomes the sign's new route and
// point, and through a sign 2 (ALWAYS_TAKE) a step on against `b` too and
// another look. The steps counted, or 0 when a look runs off its route.
int32_t chopper_find_previous_fork(struct Chopper *h,
                                   NearestRoutePointInfo *info, int b);

// 0x001e8990. From `in`'s previous fork, up to twice its count of points
// towards `b` (GetRelativePoint) for one nearer the helicopter than
// `maxd`: 1 with it in `out`, else 0.
int32_t chopper_switch_to_nearby_fork(struct Chopper *h,
                                      NearestRoutePointInfo *out,
                                      const NearestRoutePointInfo *in, int b,
                                      float maxd);

// 0x001e8a80. The target, ChopperPoint's position.
void chopper_target_chopper_point(struct Chopper *h, ChopperTarget *t);

// 0x001e8a98. Towards `point` on `route`. When ChopperPoint is it, or
// further off than CalcMinRouteFollowDistance (then at SetFollowSpeed),
// the target is ChopperPoint. Otherwise of up to five points towards it
// (FindPointsToTarget, by way of a nearby fork when there are none), the
// first that is `point` or further off than that distance, else the last;
// at SetFollowSpeed unless it is `point`. With no points, the target
// stays.
void chopper_follow_route(struct Chopper *h, ChopperTarget *t,
                          TrackRoute *route, TrackRoutePoint *point, int fwd);

// 0x001e8ce8. On from `point` (GetNextRoutePoint) to the first signpost
// that is not NoStakeout, past points marked TRP_NO_HELISHEET; with none,
// BailToPointNearChopper. The stakeout is the sign's own point when it is
// Backwards, else where it leads. When the stakeout's route has a point
// within 400 of the helicopter further along than the stakeout, the
// helicopter's own point is the target instead. Otherwise
// HEAD_TO_STAKEOUT, a 60 timeout, and FollowRoute there.
void chopper_begin_stakeout(struct Chopper *h, ChopperTarget *t,
                            TrackRoute *route, TrackRoutePoint *point);

// 0x001e8e70. The target pulled towards `point` in its frame, 0.7 of the
// way along and across at a time (GetPosition), until it is over the
// sheet. `route` is unused.
//
// The divergence: when both have shrunk below the least normal float (or
// are NaN) and it is still off the sheet, the port stops there, at the
// point itself. The EE has flushed them to zero by then, and the image
// tries that spot for ever.
void chopper_hangout_near_here(struct Chopper *h, ChopperTarget *t,
                               TrackRoute *route, TrackRoutePoint *point);

// 0x001e8f30. HangoutNearHere at the helicopter's own point.
void chopper_bail_to_point_near_chopper(struct Chopper *h,
                                        ChopperTarget *t);

// 0x001e8f40. Speed * 0.1 (gp-28044), at least 30.
float chopper_calc_min_route_follow_distance(struct Chopper *h,
                                             ChopperTarget *t);

// 0x001e8f70. Up to three times: the sheet 4.5 either side of the target
// on each axis (TestLocation), and the target 1.5 towards a side that is
// on it when the other is not. 1 once nothing moves, else 0.
int32_t chopper_adjust_target_in_bounds(struct Chopper *h,
                                        ChopperTarget *t);

// 0x001e90f0. 1 when `route` is not the helicopter's and is the one its
// previous fork (FindPreviousFork, forwards) came off. `point` is unused.
int32_t chopper_on_different_fork(struct Chopper *h, TrackRoute *route,
                                  TrackRoutePoint *point);

// 0x001e9368. The target made relative to the helicopter and turned into
// its frame (RotateToChopperCoord).
void chopper_adjust_target_local(struct Chopper *h, ChopperTarget *t);

// 0x001e98d0. FindZValue at (x, y) turned by Yaw and moved to CurrentPos.
int32_t chopper_test_location(struct Chopper *h, float x, float y);

// 0x001e9940. f * 100.
float chopper_adjust_by_think_time(struct Chopper *h, float f);

// ---- the plans (12k-3b)

// 0x001e9150. The PURSUIT plan. Still moving up or down, and over a flag-2
// polygon or off the sheet, it holds where it is. Otherwise, from the
// first of the car's points on that the target has not passed
// (FindClosestPointAhead), or the car's own:
//   - on the sheet and within CalcMinRouteFollowDistance: above speed 20,
//     the target is moved onto the point's line, along it;
//   - off the sheet at a TRP_NO_HELISHEET point, or on a different fork:
//     BeginStakeout there;
//   - else HangoutNearHere when near, or FollowRoute, forwards when the
//     helicopter is behind the car.
// With no route or point for the car, BailToPointNearChopper.
void chopper_clever_pursuit_plan(struct Chopper *h, ChopperTarget *t,
                                 int32_t on_sheet, uint32_t flags);

// 0x001e9398. The BOMBING_RUN plan. The car's progress since the last
// call goes into TargetDistance: less when it moved forward or to another
// route. Then AdjustBombTarget. A salvo is due when the last one's delay
// has run out (gp-28040 a call), or, before the first, when the
// helicopter is within 30 of the target and over the road at its own
// point. It fires (FireSalvo) when it is over the sheet and within 10 of
// the ground: Timeout back to 25, the next delay from the table, and
// PURSUIT after the last. PURSUIT too when Timeout has run out; else
// FollowRoute to the target.
//
// The port's: with the car's point or the last one NULL, the progress is
// skipped and the old point kept. The image reads address 0.
void chopper_bomb_run_logic(struct Chopper *h, ChopperTarget *t);

// 0x001e9648. The plans, once a think. Timeout less 0.1 (gp-28036), not
// below 0. The target, unless ending the chase: the car's position plus
// 0.3 (gp-28032) of its velocity, and whether that is over the sheet.
// FindChopperRoutePoint unless starting the chase. DesiredSpeed -1, then
// by plan:
//   - BOMBING_RUN: BombRunLogic;
//   - HEAD_TO_STAKEOUT and AT_STAKEOUT: PURSUIT once the target is on the
//     sheet and within 60 or Timeout has run out. Heading there, it
//     arrives within 30 of the stakeout's point (AT_STAKEOUT, Timeout 45,
//     the target the point) or follows the route to it;
//   - START_CHASE and END_CHASE: their logic, and 1 when it says so.
// PURSUIT, as it is by then, runs CleverPursuitPlan. Then
// AdjustTargetInBounds and AdjustTargetLocal, and 0.
int32_t chopper_high_level_planning(struct Chopper *h, ChopperTarget *t);

// ---- flying (12k-4a)

// 0x001e9950. The forward acceleration: toward DesiredSpeed by 10 a unit
// when it is above 0 and the target is ahead; else AdjustByThinkTime of
// the target's x less 0.1 (gp-28028) of the speed. Then no lower than
// GetMaxDeceleration, which it calls again to set it, and no higher than
// 20.
void chopper_set_x_accel(struct Chopper *h, ChopperTarget *t);

// 0x001e9a20. The sideways acceleration: 0 from 90 degrees off the nose
// (`angle`), else AdjustByThinkTime of the target's y. DesiredRoll is 0,
// or past 5 of acceleration either way, what is past 5, at most 20, the
// acceleration's sign.
void chopper_set_y_accel(struct Chopper *h, ChopperTarget *t, float angle);

// 0x001e9ae8. RotRate is `rot` within `scale` times 90 either way, and
// DesiredRoll 0.
void chopper_set_rotate_target(struct Chopper *h, float rot, float scale);

// 0x001e9b30. At most 0.001 (gp-28024) in speed, within 5 of the target
// and below 0.1 (gp-28020) of forward acceleration, the helicopter turns
// to face the car's way: in PURSUIT its heading, else bATan's to it from
// the helicopter. MoveMode ROTATE, SetRotateTarget by MakeRelativeAngle of
// Yaw - (360 - that) at scale 1, and 1. Else 0.
int32_t chopper_hover_time(struct Chopper *h, ChopperTarget *t);

// 0x001e9c68. Looks 0.1 (gp-28012) of the speed and 0.05 (gp-28016) of
// the acceleration ahead with TestLocation. Off the sheet 4.5 to +y,
// the sideways acceleration loses 0x3e999999 (gp-28008) of the speed;
// else off it 4.5 to -y, it gains that. Off the sheet 4.5 ahead, the
// forward acceleration loses it.
void chopper_check_momentum_within_bounds(struct Chopper *h);

// 0x001e9d48. MoveMode PURSUIT, then the plans; their 1, or HoverTime's,
// ends it. With the target MakeRelativeAngle(bATan) degrees off the nose,
// a helicopter at most 0.001 (gp-28004) in speed with that over 20 turns
// on the spot: MoveMode ROTATE and SetRotateTarget at scale 2. Else
// SetYAccel, SetXAccel and CheckMomentumWithinBounds.
void chopper_think(struct Chopper *h);

// 0x001e9e40. Moves *cur toward *target by `step`, or by the gap when that
// is less.
void chopper_calc_chopper_rotation(struct Chopper *h, float step,
                                   const float *target, float *cur);

// 0x001e9e80. Yaw less `f`; then 360 more when that is below 0, or 360
// less when above 360.
void chopper_subtract_from_yaw(struct Chopper *h, float f);

// ---- moving (12k-4b)

// MunitionEffectsHandler::DoTimestep (0x001bfa38) on TheMunitionEffectsHandler
// (gp-18384), which Fly calls each step: the munitions' (12k-6). NULL skips
// it.
extern void (*gMunitionEffectsDoTimestepFn)(float dt);

// 0x001e9ee8. One step of `dt`:
//   - ROTATE turns by RotRate. Moving in z by more than 0.001 (gp-28000)
//     a second, it moves, and falling, stops on the sheet.
//   - PURSUIT speeds up by the forward acceleration, within 0 .. 100, and
//     wants a pitch of 0.15 (gp-27996) of the speed, at most 20. A
//     sideways step over 0.001 (gp-27992) above a speed of 1 turns it by
//     bATan(Speed, step) degrees, less 360 from 180, times dt. It steps
//     Speed along Yaw times dt. Off the sheet it tries again 5 degrees
//     toward ChopperPoint's side (TimeUntilThink 0), and gives up in place
//     on the fourth miss. Then z: the sheet's, or moving by ZVelocity and
//     falling, no lower than the sheet. EmitDust is the polygon's flag
//     bit 0 clear; SetInterestBBox(pos, 1, step), FindGroundHeight and the
//     TP's UpdatePosition.
// Both ease the pitch and roll to their wants at 20 a second (CalcChopper
// Rotation) and CalcMatrix. 0 after four misses, else 1. A NULL
// ChopperPoint is on neither side, where the image reads address 0.
int32_t chopper_move(struct Chopper *h, float dt);

// 0x001ea5c0. The dust emitters' LocalWorld at (CurrentPos.x, y, GroundZ),
// each triggered in WorldEffects for -(11 - height over the ground) * 0.1
// (gp-27976) * dt, that share no more than 1; nothing for none.
void chopper_trigger_dust_emitter(struct Chopper *h, float dt);

// 0x001ea3b0. The WorldObject's update, and with EmitDust the dust.
void chopper_draw(struct Chopper *h, float dt);

// 0x001ea6c8. With New960, FollowThisCar of World's car 0 when it is not
// CurrentCar. The image's two tweaker triggers (gp-17172 and gp-17168:
// follow a car, drop a smoke bomb) are the debug tweaker's alone, never
// set in code, and are left out.
void chopper_do_tweaker_triggers(struct Chopper *h);

// 0x001ea7d0. DoTweakerTriggers and the munitions' step; nothing more in
// EATING_DONUTS. TimeUntilThink less dt, and below 0, 0.1 (gp-27972) more
// and Think. Unless START_CHASE then: MoveChopper and DrawChopper. A move
// zeroes StuckTime; a failed one adds dt to it, and from 0.5 it is 0 and
// the plan END_CHASE.
void chopper_fly(struct Chopper *h, float dt);

// 0x001ea8c0, in chopperfire.c. One salvo of the run's munitions: 12k-6's.
void chopper_fire_salvo(struct Chopper *h);

#endif
