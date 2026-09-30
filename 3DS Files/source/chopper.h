// chopper -- the police helicopter's head, as far as the orbit camera
// reads it.
//
// Chopper is task 26's. The demo's is 752 bytes (.mdebug type#2444), and
// retail's is longer: its TopologyCoordinate is 704 bytes where the
// demo's was 560, so everything after it is 144 further on, and it keeps
// a matrix at 848 where the demo's GetMatrix built one.
// OrbitCarCameraMover::Update (0x00158298) reads Plan, CurrentPos and
// Matrix through World's Helicopter. The rest are holes, and the struct
// is left open at the end like player.h's: nothing in the port builds a
// chopper yet, so World's Helicopter stays NULL.

#ifndef CHOPPER_H
#define CHOPPER_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "topology.h"

// ChopperPlan, .mdebug t5264.
typedef int32_t ChopperPlan;
#define CHOPPLAN_PURSUIT          ((ChopperPlan)0)
#define CHOPPLAN_HEAD_TO_STAKEOUT ((ChopperPlan)1)
#define CHOPPLAN_AT_STAKEOUT      ((ChopperPlan)2)
#define CHOPPLAN_START_CHASE      ((ChopperPlan)3)
#define CHOPPLAN_BOMBING_RUN      ((ChopperPlan)4)
#define CHOPPLAN_END_CHASE        ((ChopperPlan)5)
#define CHOPPLAN_EATING_DONUTS    ((ChopperPlan)6)

struct Chopper {
    void              *pChopperSound;   //   0  xsSound3d *
    void              *WorldObj;        //   4
    TopologyCoordinate TopologyCoord;   //   8
    uint8_t            _hole712[16];    // 712  DustEmitters .. CurrentCar
    ChopperPlan        Plan;            // 728
    uint8_t            _hole732[100];   // 732  MoveMode .. Timeout
    bVector3           CurrentPos;      // 832
    bMatrix4           Matrix;          // 848  retail's
    // ... to the end.
};

// Two pointers lead and the TopologyCoordinate's table widens on a 64-bit
// host, so the offsets are counted from its size there.
#define CHOPPER_PLAN_AT (2 * sizeof(void *) + TOPOLOGY_SIZEOF + 16)

typedef char chopper_layout_check[
    (offsetof(struct Chopper, TopologyCoord) == 2 * sizeof(void *)
     && offsetof(struct Chopper, Plan) == CHOPPER_PLAN_AT
     && offsetof(struct Chopper, CurrentPos) == CHOPPER_PLAN_AT + 104
     && offsetof(struct Chopper, Matrix) == CHOPPER_PLAN_AT + 120
     && (sizeof(void *) != 4 || CHOPPER_PLAN_AT == 728))
    ? 1 : -1];

#endif
