// copdriver -- CopDriver and CopMover, retail's copdriver.obj
// (0x001a0dd8 .. 0x001a2eec).
//
// So far the record alone: tAICop's constructor (cop.c) sets a new cop
// car's driver to parked and gives it the cop's number. The constructor,
// Think and the mover are step 12's later slices.

#ifndef COPDRIVER_H
#define COPDRIVER_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "carcontroller.h"

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

#endif
