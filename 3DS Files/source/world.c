// world -- see world.h. The globals, and the World.obj methods the port has
// reached, until task 26 brings the rest.

#include "world.h"

#include <math.h>

World  *pCurrentWorld;

// `min.s`, fs then ft.
static float min_s(float fs, float ft)
{
    return ft < fs ? ft : fs;
}

// `vsub.xyzw ; vmul.xyz ; vaddy.x ; vaddz.x`, then `sqrt.s`.
static float distance3(const bVector3 *p, const bVector3 *q)
{
    float dx = p->x - q->x;
    float dy = p->y - q->y;
    float dz = p->z - q->z;

    return sqrtf((dx * dx + dy * dy) + dz * dz);
}

float world_get_distance_to_closest_player(const World *w, const bVector3 *p)
{
    float d0 = distance3(p, &w->PlayerPositions[0]);
    float d1 = distance3(p, &w->PlayerPositions[1]);

    return min_s(d0, d1);
}

float world_get_distance_to_closest_player_2d(const World *w,
                                              const bVector2 *p)
{
    float x = p->x;
    float y = p->y;
    float dx0 = x - w->PlayerPositions[0].x;
    float dy0 = y - w->PlayerPositions[0].y;
    float d0 = sqrtf(dx0 * dx0 + dy0 * dy0);
    float dx1 = x - w->PlayerPositions[1].x;
    float dy1 = y - w->PlayerPositions[1].y;
    float d1 = sqrtf(dx1 * dx1 + dy1 * dy1);

    return min_s(d0, d1);
}
