// copmanager -- see copmanager.h.

#include "copmanager.h"

#include <math.h>

#include "car.h"
#include "eefpu.h"
#include "replay.h"

tCopManager *pCopManager;       // 0x00331bec

tCop *(*gCopManagerGetCopByCarFn)(tCopManager *m, struct Car *c);
tCop *(*gCopManagerGetCopByChaseFn)(tCopManager *m, struct Car *c);

int32_t copmanager_should_display_busted_text(const tCopManager *m)
{
    const tCarPulloverInfo *pl = (const tCarPulloverInfo *)(const void *)
        ((const uint8_t *)m + COPMANAGER_PULLOVERS);
    int i;

    for (i = 0; i < COPMANAGER_NUM_PULLOVERS; i++)
        if (pl[i].bActive && pl[i].bShouldDisplayBustedText)
            return 1;
    return 0;
}

tPursuit *copmanager_is_being_pursued(tCopManager *m, struct Car *c)
{
    tPursuitNode *list = &copmanager_head(m)->PursuitList;
    tPursuitNode *n;

    for (n = list->Next; n != list; n = n->Next)
        if (((tPursuit *)(void *)n)->pChasedCar == c)
            return (tPursuit *)(void *)n;
    return NULL;
}

int32_t copmanager_get_pursuit_level_for_hud(tCopManager *m, struct Car *c)
{
    tPursuit *p = copmanager_is_being_pursued(m, c);

    return p != NULL ? p->nHUDPursuitLevel : 0;
}

int32_t copmanager_get_num_tickets(tCopManager *m, struct Car *c)
{
    const tCarPulloverInfo *pl = (const tCarPulloverInfo *)(const void *)
        ((const uint8_t *)m + COPMANAGER_PULLOVERS);

    return pl[c->CarIndex].nNumTickets;
}

int32_t copmanager_get_num_active_road_blocks(tCopManager *m)
{
    tPursuitNode *list = &copmanager_head(m)->PursuitList;
    tPursuitNode *n;
    int32_t       count = 0;

    for (n = list->Next; n != list; n = n->Next)
        if (((tPursuit *)(void *)n)->pRoadBlock != NULL)
            count++;
    return count;
}

tRoadBlock *copmanager_get_active_road_block(tCopManager *m, int32_t i)
{
    tPursuitNode *list = &copmanager_head(m)->PursuitList;
    tPursuitNode *n;
    int32_t       k = 0;

    for (n = list->Next; n != list; n = n->Next) {
        tRoadBlock *rb = ((tPursuit *)(void *)n)->pRoadBlock;

        if (rb == NULL)
            continue;
        if (k == i)
            return rb;
        k++;
    }
    return NULL;
}

void copmanager_do_road_block_pointer_snapshot(tCopManager *m,
                                               ReplaySnapshot *s,
                                               tRoadBlock **pp)
{
    int32_t n = -1;

    if (*pp != NULL)
        n = (int32_t)(*pp - m->RoadBlocks);
    ReplaySnapshot_MoveInt(s, &n, 1);
    if (s->RestoringSnapshotFlag)
        *pp = n < 0 ? NULL : &m->RoadBlocks[n];
}

bVector2 *tpursuithistory_velocity_at(bVector2 *out, const tPursuitHistory *h,
                                      float t)
{
    bVector2 r = h->v2Velocity[0];
    float    acc = 0.0f;
    int32_t  i;

    for (i = 0; i < h->nCount; i++) {
        float ft = h->fTime[i];

        acc += ft;
        if (t <= acc) {
            if (i < h->nCount - 1) {
                const bVector2 *a = &h->v2Velocity[i];
                const bVector2 *b = &h->v2Velocity[i + 1];
                float dx, dy;

                acc -= h->fTime[0];
                dx = ee_div(a->x - b->x, ft);
                dy = ee_div(a->y - b->y, ft);
                r.x = a->x + dx * acc;
                r.y = a->y + dy * acc;
            }
            break;
        }
    }
    *out = r;
    return out;
}

int32_t tpursuit_not_in_chasing_state(const tPursuit *p)
{
    return (uint32_t)(p->PursuitState - EPS_SPEEDER_CAUGHT) < 2u;
}

int32_t tpursuit_about_to_say_something(const tPursuit *p)
{
    const Car *car;

    if (8.0f < p->fRoadBlockSpawnTimer)
        return 1;
    if (p->PursuitState == EPS_LEVEL0)
        return 1;
    if (p->PursuitState == EPS_LEVEL2 && p->fPursuitStateTimer < 13.0f)
        return 1;
    car = p->pChasedCar;
    if ((int8_t)car->BlownTireBits != 0)
        return 1;
    if (p->pRoadBlock != NULL) {
        float dx = p->pRoadBlock->v2Position.x - car->State.Position.x;
        float dy = p->pRoadBlock->v2Position.y - car->State.Position.y;

        if (sqrtf(dx * dx + dy * dy) < 150.0f)
            return 1;
    }
    return p->ChopperState == ECS_CHOPPER_REQUESTED;
}
