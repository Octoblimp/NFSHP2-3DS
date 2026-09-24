// collisionbody -- see collisionbody.h.

#include "collisionbody.h"

#include <stdio.h>
#include <stdlib.h>

#include "car.h"
#include "mellowmover.h"
#include "physicscar.h"

void carcollisionbody_setup_physics_pointers(CarCollisionBody *b)
{
    DynamicCollisionBody *d = &b->Dynamic;
    Car *car;

    d->pSystem = NULL;
    d->pBody = NULL;
    if (d->PhysicsMode == 0)
        return;

    car = b->pCar;
    if (car->TheMovementMode != PHYSICS_MOVEMENT
        && car->TheMovementMode != MELLOW_MOVEMENT)
        return;
    if (car->pCarMover == NULL) {
        fprintf(stderr, "carcollisionbody_setup_physics_pointers: "
                        "no mover\n");
        abort();
    }

    // The image does not look at which of the two it is: both put the
    // PhysicsSystem at 8 and the RigidBody at 24.
    if (car->TheMovementMode == PHYSICS_MOVEMENT) {
        PhysicsCar *pc = (PhysicsCar *)car->pCarMover;
        d->pSystem = &pc->Vehicle;
        d->pBody = pc->pBody;
    } else {
        MellowMover *mm = (MellowMover *)car->pCarMover;
        d->pSystem = &mm->Vehicle;
        d->pBody = mm->pBody;
    }
}

void carcollisionbody_set_to_physics_mode(CarCollisionBody *b,
                                          CollisionBody *other)
{
    Car *them = NULL;

    if (other != NULL && other->Type == 0)
        them = ((CarCollisionBody *)other)->pCar;
    car_set_to_physics_mode(b->pCar, them);
    carcollisionbody_setup_physics_pointers(b);
}
