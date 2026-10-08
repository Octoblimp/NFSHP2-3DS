// coputil -- see coputil.h.

#include "coputil.h"

#include <math.h>

#include "car.h"
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

int32_t car_in_recent_collision(Car *car)
{
    return car->pDynamicCollisionBody->Dynamic.Body.NumCollisions != 0;
}
