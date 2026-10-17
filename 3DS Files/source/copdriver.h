// copdriver -- CopDriver and CopMover, retail's copdriver.obj
// (0x001a0dd8 .. 0x001a2eec).
//
// CopMover is the mover a cop car rides when no player is near: no
// physics, just a speed and a heading (eCMS_STEERING) or a velocity
// (eCMS_TRANSLATING) eased towards what the CopDriver asks for, held to the
// ground under the car. CopDriver is the controller that asks: parked,
// patrolling along the cop's own drive target, chasing (steering for a
// point on the pursuit's targets, or translating alongside the chased car
// when close and as fast), or backing up when stuck. Both are all here but
// CopDriver's CollisionAvoidance, which nothing calls; the DoSnapshots are
// the replay's, since TASKS 72c. See
// docs/formats/cop-mover.md and docs/formats/cop-driver.md.

#ifndef COPDRIVER_H
#define COPDRIVER_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "carcontroller.h"
#include "drivetarget.h"
#include "physicscar.h"    // CarMover

struct Car;

// eCopDriverStates, .mdebug t1466.
typedef int32_t eCopDriverStates;
#define eCDS_DISABLED    ((eCopDriverStates)0)
#define eCDS_PARKED      ((eCopDriverStates)1)
#define eCDS_PATROLLING  ((eCopDriverStates)2)
#define eCDS_PURSUIT     ((eCopDriverStates)3)
#define eCDS_BACKING_UP  ((eCopDriverStates)4)

// CopDriver, .mdebug t1468, 76 bytes in both images: a TrackedController
// and nine words.
typedef struct CopDriver {
    TrackedController Base;                     //  0
    eCopDriverStates  State;                    // 36
    eCopDriverStates  StateBeforeGettingStuck;  // 40
    int32_t           SubState;                 // 44
    float             fStuckTimer;              // 48
    float             fBackingUpTimer;          // 52
    float             fPatrolSpeed;             // 56
    int32_t           nCopIndex;                // 60
    bVector2          v2SteerTarget;            // 64
    int32_t           nCarClass;                // 72
} CopDriver;                                    // 76

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char copdriver_layout_check[
    (offsetof(CopDriver, State) == 36 && offsetof(CopDriver, nCopIndex) == 60
     && offsetof(CopDriver, nCarClass) == 72 && sizeof(CopDriver) == 76)
    ? 1 : -1];
#endif

// _vt$9CopDriver, 0x002b5998, TrackedController's layout: its own
// destructor (0x001a1e30), DoSnapshot (0x001a2b58) and Think (0x001a2110),
// and the rest TrackedController's and CarController's.
#define COPDRIVER_VTABLE     0x002b5998u

// A DLOffset: x along the drive target, y across it (to the right of the
// way it runs).
typedef bVector2 DLOffset;

// 0x001a1ce8, `__9CopDriverP3Car`. A TrackedController with its own
// table, and a NullDriver for its Driver (bMalloc'd as "NullDriver" and
// built as CarDriver's constructor builds one, with DesiredGear -1).
// Parked, StateBeforeGettingStuck parked, SubState 1, both timers 0, no
// cop (-1), the steer target at the origin, and patrolling at 65 mph.
// nCarClass by the car type's Type: 0 for 32, 1 for 33, 2 for 34, 3 for
// 31 and 4 for 4; any other leaves it as it was.
CopDriver *copdriver_init(CopDriver *d, struct Car *car);

// carmodes.h's CarControllerCtorFn: the constructor on memory Car
// allocated.
CarController *copdriver_construct(void *mem, struct Car *car);

// 0x001a1e30: its own vptr, `delete` the Driver through its table (flags
// 3), then ~TrackedController with this call's flags.
void copdriver_destroy(CopDriver *d, int32_t flags);

// 0x001a2110. TrackedController's Think, then, on COP_MOVEMENT only, the
// state's asks of the car's CopMover. See docs/formats/cop-driver.md.
void copdriver_think(CopDriver *d, float dt);

// 0x001a1e90. Where the cop steers in a pursuit, by its sub-state: a point
// on the pursuit's near or far drive target, or on one built along the
// chased car's route or its own. Nothing without a pursuit.
void copdriver_get_pursuit_target_point(CopDriver *d, bVector2 *out);

// 0x001a2a90. After a collision, while patrolling or chasing: under 2 m/s
// the stuck timer climbs, and past 1 s the car is stuck. Otherwise the
// timer goes back to 0.
int32_t copdriver_are_we_stuck(CopDriver *d, float dt);

// 0x001a2c30, `FindDriveTargetPointByDistance`. Finds the segment of `t`
// that `pos` lies alongside, from the last, and the point `dist` on from
// it along the target, moved by `off` along and across the segment it is
// on; *lateral is how far `pos` is across from it. Returns 1, or 0 with
// the second point (the first, for fewer than two) and *lateral unset.
int32_t copdriver_find_point_by_distance(bVector2 *out, float *lateral,
                                         const DriveTarget *t,
                                         const bVector2 *pos, float dist,
                                         const DLOffset *off);

// 0x001a2ef0, `GetDriveTargetPointByDLOffsetFromStart`. Walks back from
// the target's last point off->x along it and moves off->y across the
// segment it ends on. Fewer than two points give the last.
void copdriver_get_point_by_dl_offset_from_start(bVector2 *out,
                                                 const DriveTarget *t,
                                                 const DLOffset *off);

// The inline accessors, 0x001a32d0 .. 0x001a32e8. GetRouteNumbersToUse is
// empty.
void copdriver_get_route_numbers_to_use(CopDriver *d, int32_t *a,
                                        int32_t *b);
void copdriver_set_patrol_speed(CopDriver *d, float s);
void copdriver_set_state(CopDriver *d, eCopDriverStates s);
void copdriver_set_cop_index(CopDriver *d, int32_t n);

// ------------------------------------------------------------- CopMover

// eCopMoverState, .mdebug t1446: a speed along a heading, or a velocity.
typedef int32_t eCopMoverState;
#define eCMS_STEERING     ((eCopMoverState)0)
#define eCMS_TRANSLATING  ((eCopMoverState)1)

// CopMover, retail's 128 bytes (the demo's .mdebug t2698 is 112). Retail
// put sixteen bytes in at 64: New64 is a ramp from 0 to 1 that braking
// climbs at two a second and how hard it may brake scales with; 68 to 79
// are never read or written here. The port's bVector3 is word-aligned, so
// the padding the image has before each is spelled out.
typedef struct CopMover {
    CarMover       Mover;                   //   0  Driver 0, vptr 4
    struct Car    *pCar;                    //   8
    uint32_t       _pad12;                  //  12 the image's, to 16: its
                                            //     bVector3s are quadwords
    bVector3       v3Velocity;              //  16
    bVector2       v2TransverseAccel;       //  32
    uint16_t       aFacingAngle;            //  40
    uint16_t       aDesiredFacingAngle;     //  42
    float          fSpeed;                  //  44
    float          fDesiredSpeed;           //  48
    float          fBaseMaxSpeed;           //  52
    float          fMaxBrakingAccel;        //  56
    float          fMaxThrottleAccel;       //  60
    float          New64;                   //  64 the braking ramp
    float          New68[3];                //  68
    bVector3       v3DesiredVelocity;       //  80
    bVector3       v3GroundNormal;          //  96
    int32_t        bIsAirborne;             // 112
    eCopMoverState State;                   // 116
    int32_t        _pad120[2];              // 120 to the sixteen
} CopMover;                                 // 128

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char copmover_layout_check[
    (offsetof(CopMover, pCar) == 8 && offsetof(CopMover, v3Velocity) == 16
     && offsetof(CopMover, aFacingAngle) == 40
     && offsetof(CopMover, fMaxThrottleAccel) == 60
     && offsetof(CopMover, New64) == 64
     && offsetof(CopMover, v3DesiredVelocity) == 80
     && offsetof(CopMover, v3GroundNormal) == 96
     && offsetof(CopMover, State) == 116 && sizeof(CopMover) == 128)
    ? 1 : -1];
#endif

// _vt$8CopMover, 0x002b5a08, CarMover's layout: the destructor (0x001a0e88),
// Move (0x001a1030) and DoSnapshot (0x001a0f20).
#define COPMOVER_VTABLE     0x002b5a08u
#define COPMOVER_VT_ENTRIES 4

// 0x001a0dd8, `__8CopMoverP3Car`. Every word but the Driver, which
// SetMovementMode's tail stores, and 68 to 79: steering, the car's
// velocity (as the one wanted too), its forward speed and heading (as the
// ones wanted too), a top speed of 84.935 m/s, ResetMaxThrottleAccel,
// braking at 40 m/s/s, no sideways acceleration, the ground straight up,
// on the ground, and the ramp at 0. The normal's fourth word is the
// image's stack; the port's is 0.
CopMover *copmover_init(CopMover *m, struct Car *car);

// carmodes.h's CarMoverCtorFn: the constructor on memory Car allocated.
CarMover *copmover_construct(void *mem, struct Car *car);

// 0x001a0e88: its own vptr, then ~CarMover with this call's flags.
void copmover_destroy(CopMover *m, int32_t flags);

// 0x001a0ea0. fMaxThrottleAccel by the car type's Type: 11.25 for 4, 12.75
// for 31, 15 for 32 and 33, 14.25 for 34; any other leaves it as it was.
void copmover_reset_max_throttle_accel(CopMover *m);

// 0x001a1030. One frame; see docs/formats/cop-mover.md. Returns dt.
float copmover_move(CopMover *m, float dt);

// 0x001a1bd0. Turns aFacingAngle towards aDesiredFacingAngle at a rate the
// speed sets, no more than `max_speed` allows; returns the rate, in BAM a
// second.
float copmover_calculate_facing_angle(CopMover *m, float max_speed, float dt);

// The inline accessors, 0x001a32f0 .. 0x001a3344. SetDesiredVelocity
// keeps x, y and the fourth word and zeroes z.
const bVector2 *copmover_get_transverse_accel(const CopMover *m);
int32_t copmover_is_airborne(const CopMover *m);
void    copmover_set_max_throttle_accel(CopMover *m, float a);
void    copmover_set_max_brake_accel(CopMover *m, float a);
void    copmover_set_base_max_speed(CopMover *m, float s);
float   copmover_get_max_speed(const CopMover *m);
void    copmover_set_desired_velocity(CopMover *m, const bVector3 *v);
void    copmover_set_desired_speed(CopMover *m, float s);
void    copmover_set_desired_angle(CopMover *m, uint16_t a);
void    copmover_set_state(CopMover *m, eCopMoverState s);

// The replay's (TASKS 72c), slot 24 of each table. 0x001a0f20, a
// "CopMover" section: CarMover's (nothing), the velocity, both angles, the
// speeds, the wanted velocity, State's low byte, both accelerations, the
// ground normal, the airborne flag, the transverse acceleration and the
// braking ramp. 0x001a2b58, a "CopDriver" section begun with the object:
// the TrackedController, the three states' low bytes, the three timers and
// speed, the steer target and the cop index as one signed byte.
struct ReplaySnapshot;
void copmover_do_snapshot(CopMover *m, struct ReplaySnapshot *s);
void copdriver_do_snapshot(CopDriver *c, struct ReplaySnapshot *s);

// Installs the table. The game calls it once at boot; a harness calls it
// after vt_reset().
void copmover_install_vtables(void);

// Points carmodes.h's gCopMoverCtorFn at this file.
void copmover_install_seams(void);

// CopDriver's, likewise, and gCopDriverCtorFn.
void copdriver_install_vtables(void);
void copdriver_install_seams(void);

#endif
