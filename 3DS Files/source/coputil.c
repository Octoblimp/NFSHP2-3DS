// coputil -- see coputil.h.

#include "coputil.h"

#include "car.h"
#include "collisionbody.h"

int32_t car_in_recent_collision(Car *car)
{
    return car->pDynamicCollisionBody->Dynamic.Body.NumCollisions != 0;
}
