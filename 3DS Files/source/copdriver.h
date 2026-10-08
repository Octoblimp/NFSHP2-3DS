// copdriver -- CopDriver and CopMover, retail's copdriver.obj
// (0x001a0dd8 .. 0x001a2eec).
//
// CopMover is the mover a cop car rides when no player is near: no
// physics, just a speed and a heading (eCMS_STEERING) or a velocity
// (eCMS_TRANSLATING) eased towards what the CopDriver asks for, held to the
// ground under the car. It is all here but DoSnapshot. CopDriver is the
// record alone so far: tAICop's constructor (cop.c) sets a new cop car's
// driver to parked and gives it the cop's number. Its constructor and
// Think are step 12's later slices. See docs/formats/cop-mover.md.

#ifndef COPDRIVER_H
#define COPDRIVER_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "carcontroller.h"
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
// Move (0x001a1030) and DoSnapshot (0x001a0f20, not ported: a NULL entry,
// which vt_slot aborts on).
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

// Installs the table. The game calls it once at boot; a harness calls it
// after vt_reset().
void copmover_install_vtables(void);

// Points carmodes.h's gCopMoverCtorFn at this file.
void copmover_install_seams(void);

#endif
