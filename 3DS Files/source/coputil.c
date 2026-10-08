// coputil -- see coputil.h.

#include "coputil.h"

#include <math.h>

#include "car.h"
#include "collision.h"
#include "collisionbody.h"
#include "trackpath.h"
#include "world.h"

float get_forward_track_distance(float a, float b)
{
    float d = a - b;

    if (d < 0.0f)
        d += TheTrackPathManager.TrackLength;
    return d;
}

// The cars' distances are `sqrt.s` of the squares summed x, then y. The
// count is read again on every pass.
int32_t is_teleport_location_clear(const bVector2 *p)
{
    World *w = pCurrentWorld;
    int32_t i;

    if (world_get_distance_to_closest_player_2d(w, p) < 250.0f)
        return 0;
    for (i = 0; i < pCurrentWorld->TotalNumCars; ++i) {
        const Car *c = pCurrentWorld->CarTable[i];
        float dx = p->x - c->State.Position.x;
        float dy = p->y - c->State.Position.y;

        if (sqrtf(dx * dx + dy * dy) < 15.0f)
            return 0;
    }
    return 1;
}

int32_t can_teleport(Car *car, const bVector2 *dest)
{
    World  *w = pCurrentWorld;
    int32_t n, i;

    if (world_get_distance_to_closest_player_2d(
            w, (const bVector2 *)(const void *)&car->State.Position) < 250.0f)
        return 0;
    if (world_get_distance_to_closest_player_2d(pCurrentWorld, dest)
        < 250.0f)
        return 0;
    w = pCurrentWorld;
    n = w->TotalNumCars;
    for (i = 0; i < n; i++) {
        const Car *o = w->CarTable[i];
        float      dx, dy;

        if (o == car)
            continue;
        dx = car->State.Position.x - o->State.Position.x;
        dy = car->State.Position.y - o->State.Position.y;
        if (sqrtf(dx * dx + dy * dy) < 15.0f)
            return 0;
    }
    return 1;
}

// Retail walks the collisions with an iterator whose next is the next
// two-car collision's other car, NULL past the last.
Car *car_caused_recent_collision(Car *car)
{
    CollisionBody *b = &car->pDynamicCollisionBody->Dynamic.Body;
    int32_t        i = 0;

    for (;;) {
        Car *other = NULL;

        while (i < b->NumCollisions) {
            Collision *col = collisionbody_get_collision(b, i++);

            if (collision_is_two_car_collision(col)) {
                Car *c1, *c2;

                collision_get_colliding_cars(col, &c1, &c2);
                other = c1 == car ? c2 : c1;
                break;
            }
        }
        if (other == NULL)
            return NULL;
        if (other->State.ForwardSpeed == 0.0f)
            return other;
        if (car_is_car_in_front(car, other, 8192)
            && 0.0f <= other->State.ForwardSpeed
            && other->State.ForwardSpeed < car->State.ForwardSpeed)
            return other;
    }
}

int32_t did_these_cars_collide(Car *a, Car *b)
{
    CollisionBody *body = &a->pDynamicCollisionBody->Dynamic.Body;
    int32_t        i = 0;

    for (;;) {
        Car *other = NULL;

        while (i < body->NumCollisions) {
            Collision *col = collisionbody_get_collision(body, i++);

            if (collision_is_two_car_collision(col)) {
                Car *c1, *c2;

                collision_get_colliding_cars(col, &c1, &c2);
                other = c1 == a ? c2 : c1;
                break;
            }
        }
        if (other == NULL)
            return 0;
        if (other == b)
            return 1;
    }
}

int32_t car_in_recent_collision(Car *car)
{
    return car->pDynamicCollisionBody->Dynamic.Body.NumCollisions != 0;
}
