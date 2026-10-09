// barricade -- BarricadeManager and the roadblock's plan. See barricade.h.

#include "barricade.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "collisionbody.h"
#include "copmanager.h"
#include "eefpu.h"
#include "smokeable.h"
#include "trackroute.h"
#include "vtable.h"

void (*gBarricadeDeleteBarrelFn)(int16_t id);
void (*gBarricadeMarkBodyFadingFn)(struct CollisionBody *body);
SmokeableInfo *(*gFindSmokeableInfoFn)(uint32_t hash);
int32_t (*gSmokeableSpawnFn)(int32_t type, SmokeableInfo *info,
                             uint32_t hash, const bVector3 *pos,
                             uint16_t ang);

static void unported(const char *name)
{
    fprintf(stderr, "barricade: %s is not ported\n", name);
    abort();
}

BarricadeManager *barricademanager_construct(BarricadeManager *b)
{
    int32_t i;

    b->vptr = BARRICADEMANAGER_VTABLE;
    for (i = 0; i < BARRICADE_MAX_BARRELS; i++) {
        b->nBarrel[i] = -1;
        b->fFadeTimer[i] = -1.0f;
    }
    return b;
}

void barricademanager_destruct(BarricadeManager *b, int32_t flags)
{
    int32_t i;

    b->vptr = BARRICADEMANAGER_VTABLE;
    for (i = 0; i < BARRICADE_MAX_BARRELS; i++) {
        if (b->nBarrel[i] == -1)
            continue;
        if (gBarricadeDeleteBarrelFn == NULL)
            unported("the barrel's delete (0x0021ef88)");
        gBarricadeDeleteBarrelFn(b->nBarrel[i]);
    }
    if (flags & 1)
        bFree(b);
}

int32_t barricademanager_spawn_barrel(BarricadeManager *b,
                                      const bVector3 *pos)
{
    int32_t i;

    for (i = 0; i < BARRICADE_MAX_BARRELS; i++) {
        SmokeableInfo *info;
        bVector4      *row;
        float          f;
        int32_t        r, id;

        if (b->nBarrel[i] != -1)
            continue;
        info = gFindSmokeableInfoFn != NULL
                   ? gFindSmokeableInfoFn(bchunk_hash("CS_RoadBlock_Barrel"))
                   : NULL;
        if (info == NULL)
            continue;
        // A barrel weighs 10, however the info was made; VU0 scales the
        // tensor's first three rows, all four lanes.
        f = 10.0f / info->RBI.Mass;
        info->RBI.Mass *= f;
        for (r = 0; r < 3; r++) {
            row = r == 0 ? &info->RBI.InertiaTensor.v0
                : r == 1 ? &info->RBI.InertiaTensor.v1
                         : &info->RBI.InertiaTensor.v2;
            row->x *= f;
            row->y *= f;
            row->z *= f;
            row->w *= f;
        }
        if (gSmokeableSpawnFn == NULL)
            unported("the smokeable's spawn (0x0021ed28)");
        id = gSmokeableSpawnFn(0, info, bchunk_hash("ROADBLOCK_BARREL"), pos,
                               0);
        b->nBarrel[i] = (int16_t)id;
        return id;
    }
    return -1;
}

void barricademanager_fade(BarricadeManager *b, float t)
{
    int32_t i;

    for (i = 0; i < BARRICADE_MAX_BARRELS; i++) {
        CollisionBody *body;

        if (b->nBarrel[i] == -1)
            continue;
        b->fFadeTimer[i] = t;
        body = collisionbody_find(b->nBarrel[i]);
        if (body != NULL) {
            if (gBarricadeMarkBodyFadingFn == NULL)
                unported("the barrel body's byte at 1123");
            gBarricadeMarkBodyFadingFn(body);
        }
    }
}

void barricademanager_count_down(BarricadeManager *b, float dt)
{
    int32_t i;

    for (i = 0; i < BARRICADE_MAX_BARRELS; i++) {
        if (b->nBarrel[i] == -1 || b->fFadeTimer[i] == -1.0f)
            continue;
        b->fFadeTimer[i] -= dt;
        if (b->fFadeTimer[i] < 0.0f) {
            if (gBarricadeDeleteBarrelFn == NULL)
                unported("the barrel's delete (0x0021ef88)");
            gBarricadeDeleteBarrelFn(b->nBarrel[i]);
            b->fFadeTimer[i] = -1.0f;
            b->nBarrel[i] = -1;
        }
    }
}

typedef void (*DtorFn)(void *self, int32_t flags);

static void barricademanager_dtor_entry(void *self, int32_t flags)
{
    barricademanager_destruct((BarricadeManager *)self, flags);
}

static const VtEntry barricademanager_vt[] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)barricademanager_dtor_entry },  // 8  0x0024efd8
};

void barricade_install_vtables(void)
{
    vt_install(BARRICADEMANAGER_VTABLE, barricademanager_vt,
               (int)(sizeof barricademanager_vt
                     / sizeof barricademanager_vt[0]));
}

// ------------------------------------------------------------- the plan

// 45 degrees as a BAM; 0x00250150's division by 360 is folded away but
// for its zero check.
uint16_t RoadBlockCopAngle = 8192;

RoadBlockPlan *roadblockplan_construct(RoadBlockPlan *q)
{
    q->Tail = 0;
    q->vptr = ROADBLOCKPLAN_VTABLE;
    q->Head = 0;
    return q;
}

void roadblockplan_destruct(RoadBlockPlan *q, int32_t flags)
{
    q->vptr = ROADBLOCKPLAN_VTABLE;
    if (flags & 1)
        bFree(q);
}

int32_t roadblockplan_push(RoadBlockPlan *q, uint32_t v)
{
    int32_t next = (q->Tail + 1) % RBPLAN_SIZE;

    if (next == q->Head)
        return 0;
    q->Data[q->Tail] = v;
    q->Tail = next;
    return 1;
}

int32_t roadblockplan_pop(RoadBlockPlan *q, uint32_t *out)
{
    if (q->Head == q->Tail)
        return 0;
    *out = q->Data[q->Head];
    q->Head = (q->Head + 1) % RBPLAN_SIZE;
    return 1;
}

float roadblock_cop_car_width(uint16_t ang)
{
    const tCopManager *m = pCopManager;
    float y = m->fMaxCopCarYdim, x = m->fMaxCopCarXdim;

    return fabsf(bCosBam(ang)) * y + fabsf(bSinBam(ang)) * x;
}

float roadblock_cop_car_angle(uint16_t *ang)
{
    *ang = 8192;
    return roadblock_cop_car_width(8192);
}

static uint32_t float_word(float f)
{
    uint32_t u;

    memcpy(&u, &f, sizeof u);
    return u;
}

void roadblock_build_plan(RoadBlockPlan *q, const int32_t *layout, float escW,
                          const tRoadBlock *rb)
{
    uint16_t ang = RoadBlockCopAngle;
    float    lane[2] = { 0.0f, 0.0f };
    float    total = 0.0f, road, cw, share, diff;
    int32_t  nspikes = 0, ncops = 0, nlanes = 0, segs = 8;
    int32_t  barrels = 0, nbarrels = 0;
    int32_t  i, n;

    cw = roadblock_cop_car_width(ang);
    road = rb->fRoadWidth;
    for (i = 0; layout[i] != RBPLAN_END; i++) {
        switch (layout[i]) {
        case RBPLAN_LANE_LEFT:
            lane[0] = escW;
            total += escW;
            nlanes++;
            break;
        case RBPLAN_LANE_RIGHT:
            lane[1] = escW;
            total += escW;
            nlanes++;
            break;
        case RBPLAN_GAP:
            total += 0.800000011920929f;            // gp-26452
            break;
        case RBPLAN_SPIKES:
            nspikes++;
            total += (float)segs * 0.6499999761581421f;    // gp-26448
            break;
        case RBPLAN_COP:
            ncops++;
            total += cw;
            break;
        case RBPLAN_BARRELS:
            barrels = 1;
            break;
        default:
            break;
        }
    }
    // Wider than the road: the last cop car goes, if there are two.
    if (cw < total - road && !(ncops < 2)) {
        total -= cw;
        ncops--;
    }
    // The cars turned to 45 degrees. RoadBlockCopAngle is 8192 already, so
    // this adds nothing; retail turns the count to a float, an int and a
    // float again first.
    total += (float)ncops * (roadblock_cop_car_angle(&ang) - cw);
    road = rb->fRoadWidth;
    if (barrels && 3.0f < road - total) {           // gp-14816
        n = ee_trunc_w((road - total) / 3.0f);
        if (!(n < 11))
            n = 10;
        nbarrels = n;
        total += (float)n * 3.0f;
    }
    if (nspikes != 0) {
        // gp-26444: 1/0.65, segments for the road left.
        n = ee_trunc_w((road - total) * 1.5384615659713745f);
        if (n != 0) {
            segs = n + 8;
            if (segs < 3 * nspikes)
                segs = 3 * nspikes;
            if (20 * nspikes < segs)
                segs = 20 * nspikes;
            total += (float)(segs - 8) * 0.6499999761581421f;  // gp-26440
        }
    }
    share = (road - total) / (float)nlanes;
    if (lane[0] == 0.0f || lane[1] == 0.0f) {
        lane[1] += share;
        lane[0] += share;
    } else {
        const TrackRoutePoint *rp = rb->RoutePoint;

        diff = rp->LeftWidth - rp->RightWidth;
        lane[1] += share;
        lane[0] += share;
        if (0.0f < diff) {
            if (diff < lane[1]) {
                lane[0] += diff;
                lane[1] -= diff;
            } else {
                lane[1] = 0.0f;
            }
        } else {
            diff = fabsf(diff);
            if (diff < lane[0]) {
                lane[1] += diff;
                lane[0] -= diff;
            } else {
                // Retail's: the right lane doubled, not the left one added.
                lane[0] = 0.0f;
                lane[1] += lane[1];
            }
        }
    }
    for (i = 0; layout[i] != RBPLAN_END; i++) {
        uint32_t tok = (uint32_t)layout[i];

        switch (layout[i]) {
        case RBPLAN_LANE_LEFT:
            roadblockplan_push(q, tok);
            roadblockplan_push(q, float_word(lane[0]));
            break;
        case RBPLAN_LANE_RIGHT:
            roadblockplan_push(q, tok);
            roadblockplan_push(q, float_word(lane[1]));
            break;
        case RBPLAN_GAP:
            roadblockplan_push(q, tok);
            break;
        case RBPLAN_SPIKES:
            // The segments shared out, the remainder to the last.
            roadblockplan_push(q, tok);
            n = segs / nspikes;
            nspikes--;
            segs -= n;
            roadblockplan_push(q, (uint32_t)n);
            break;
        case RBPLAN_COP:
            if (ncops != 0) {
                // Retail pushes the word at the angle's short, whose top
                // half is stack; the layout reads the short.
                roadblockplan_push(q, tok);
                roadblockplan_push(q, ang);
                ncops--;
            }
            break;
        case RBPLAN_BARRELS:
            for (n = 0; n < nbarrels; n++)
                roadblockplan_push(q, tok);
            break;
        default:
            break;
        }
    }
}
