// carmodes -- see carmodes.h.

#include "carmodes.h"

#include <stdio.h>
#include <stdlib.h>

#include "bmem.h"
#include "bslotpool.h"
#include "cardriver.h"
#include "collisionbody.h"
#include "mellowmover.h"
#include "physcomp.h"
#include "physicscar.h"
#include "vtable.h"

// ------------------------------------------------------------- NullMover

NullMover *nullmover_new(void)
{
    return (NullMover *)bSlotOMalloc(NullMoverSlotPool);
}

void nullmover_delete(void *p)
{
    bSlotFree(NullMoverSlotPool, p);
}

NullMover *nullmover_init(NullMover *m, CarState *cs)
{
    m->pState = cs;
    m->Mover._vtable = NULLMOVER_VTABLE;
    return m;
}

void nullmover_destroy(NullMover *m, int32_t flags)
{
    m->Mover._vtable = NULLMOVER_VTABLE;
    carmover_destroy(&m->Mover, 0);
    if (flags & 1)
        nullmover_delete(m);
}

float nullmover_move(NullMover *m, float dt)
{
    carstate_calculate_wheel_matrices(m->pState);
    return dt;
}

static const VtEntry nullmover_vt[NULLMOVER_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)nullmover_destroy },              //  8  0x00134bd8
    { 0, 0, (VtFn)nullmover_move },                 // 16  0x0012f1f0
    { 0, 0, (VtFn)carmover_do_snapshot },           // 24  0x0012f1e8
};

void nullmover_install_vtables(void)
{
    vt_install(NULLMOVER_VTABLE, nullmover_vt, NULLMOVER_VT_ENTRIES);
}

// ------------------------------------------------------------- the seams

CarMoverCtorFn gTrafficCarCtorFn;
CarMoverCtorFn gDeliveryMoverCtorFn;
CarMoverCtorFn gCopMoverCtorFn;
CarMoverCtorFn gBeltMoverCtorFn;

CarControllerCtorFn gRealControllerCtorFn;
CarControllerCtorFn gAIDriverCtorFn;
CarControllerCtorFn gTrafficDriverCtorFn;
CarControllerCtorFn gCopDriverCtorFn;

static void no_class(const char *name)
{
    fprintf(stderr, "carmodes: %s is not ported\n", name);
    abort();
}

// `bMalloc(size, name, 0, 16)` and the constructor on it, as each of the
// eight arms has it.
static CarMover *new_mover(CarMoverCtorFn ctor, int size, const char *name,
                           Car *car)
{
    void *mem;

    if (ctor == NULL)
        no_class(name);
    mem = bMalloc(size, name, 0, CAR_MEMORY_POOL);
    return ctor(mem, car);
}

static CarController *new_controller(CarControllerCtorFn ctor, int size,
                                     const char *name, Car *car)
{
    void *mem;

    if (ctor == NULL)
        no_class(name);
    mem = bMalloc(size, name, 0, CAR_MEMORY_POOL);
    return ctor(mem, car);
}

// --------------------------------------------------------- the four methods

typedef void (*DtorFn)(void *self, int32_t flags);
typedef void (*SetToPhysicsModeFn)(void *self, Car *other);

void car_set_control_mode(Car *c, ControlMode mode)
{
    CarController *old = c->pCarController;
    CarController *ctrl;

    // The old controller goes first, and the field is left pointing at
    // it: every arm below overwrites it.
    if (old != NULL) {
        const VtEntry *e = vt_slot(old->_vtable, CARCONTROLLER_VT_DTOR);
        ((DtorFn)e->fn)(vt_this(old, e), 3);
    }

    c->TheControlMode = mode;
    switch (mode) {
    case eNO_CONTROL:
        ctrl = &car_new_null_controller(c)->Base;
        break;
    case REAL_CONTROL:
        ctrl = new_controller(gRealControllerCtorFn, REALCONTROLLER_SIZE,
                              "RealController", c);
        break;
    case AI_CONTROL:
        ctrl = new_controller(gAIDriverCtorFn, AIDRIVER_SIZE, "AIDriver", c);
        break;
    case TRAFFIC_CONTROL:
        ctrl = new_controller(gTrafficDriverCtorFn, TRAFFICDRIVER_SIZE,
                              "TrafficDriver", c);
        break;
    case COP_CONTROL:
        ctrl = new_controller(gCopDriverCtorFn, COPDRIVER_SIZE, "CopDriver",
                              c);
        break;
    default:
        // `sltiu v0,s0,5` skips the table and runs the tail on the
        // controller just destroyed.
        fprintf(stderr, "car_set_control_mode: mode %d\n", (int)mode);
        abort();
    }
    c->pCarController = ctrl;

    c->pCarDriver = ctrl->Driver;
    c->pCarMover->Driver = c->pCarDriver;
}

void car_set_movement_mode(Car *c, MovementMode mode)
{
    CarMover *old = c->pCarMover;

    if (old != NULL) {
        const VtEntry *e = vt_slot(old->_vtable, CARMOVER_VT_DTOR);
        ((DtorFn)e->fn)(vt_this(old, e), 3);
    }

    c->TheMovementMode = mode;
    switch (mode) {
    case eNO_MOVEMENT: {
        // NullMover's new and constructor, inline: the slot comes back
        // cleared, so its Driver is zero until the tail.
        NullMover *m = nullmover_new();
        m->Mover._vtable = NULLMOVER_VTABLE;
        m->pState = &c->State;
        c->pCarMover = &m->Mover;
        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 0;
        break;
    }
    case PHYSICS_MOVEMENT: {
        PhysicsCar *pc = (PhysicsCar *)bMalloc((int)sizeof(PhysicsCar),
                                               "PhysicsCar", 0,
                                               CAR_MEMORY_POOL);
        pc = physicscar_init(pc, c->pCarTypeInfo, c->pCarDriver, c);
        pc->FrictionBoost = c->FrictionBoost;
        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 1;
        c->pCarMover = &pc->Mover;
        break;
    }
    case MELLOW_MOVEMENT: {
        MellowMover *mm = mellowmover_new();
        mm = mellowmover_init(mm, c, c->pCarTypeInfo, c->pCarDriver,
                              &c->State);
        c->pCarMover = &mm->Mover;
        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 1;
        break;
    }
    case TRAFFIC_MOVEMENT:
        c->pCarMover = new_mover(gTrafficCarCtorFn, TRAFFICCAR_SIZE,
                                 "TrafficCar", c);
        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 0;
        break;
    case DELIVERY_MOVEMENT:
        c->pCarMover = new_mover(gDeliveryMoverCtorFn, DELIVERYMOVER_SIZE,
                                 "DeliveryMover", c);
        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 0;
        break;
    case COP_MOVEMENT:
        c->pCarMover = new_mover(gCopMoverCtorFn, COPMOVER_SIZE, "CopMover",
                                 c);
        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 0;
        break;
    case BELT_MOVEMENT:
        c->pCarMover = new_mover(gBeltMoverCtorFn, BELTMOVER_SIZE,
                                 "BeltMover", c);
        c->pDynamicCollisionBody->Dynamic.PhysicsMode = 0;
        break;
    default:
        // `sltiu v0,s1,7` skips the table: the tail would store the
        // driver into the mover just destroyed.
        fprintf(stderr, "car_set_movement_mode: mode %d\n", (int)mode);
        abort();
    }

    carcollisionbody_setup_physics_pointers(c->pDynamicCollisionBody);
    c->pCarMover->Driver = c->pCarDriver;
}

void car_set_to_physics_mode(Car *c, Car *other)
{
    CarController *ctrl = c->pCarController;

    if (ctrl != NULL) {
        const VtEntry *e = vt_slot(ctrl->_vtable,
                                   CARCONTROLLER_VT_SET_TO_PHYSICS_MODE);
        ((SetToPhysicsModeFn)e->fn)(vt_this(ctrl, e), other);
        return;
    }
    // Retail's 0x00131800 inlines CarController::SetToPhysicsMode here.
    carcontroller_physics_or_mellow(c);
}

void car_set_friction_boost(Car *c, float f)
{
    c->FrictionBoost = f;
    if (c->TheMovementMode == PHYSICS_MOVEMENT)
        ((PhysicsCar *)c->pCarMover)->FrictionBoost = f;
}
