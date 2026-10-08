// copmgr -- see copmgr.h.

#include "copmgr.h"

#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "airoute.h"
#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "car.h"
#include "collision.h"
#include "collisionbody.h"
#include "configitems.h"
#include "race.h"
#include "topology.h"
#include "trackmap.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

LandmarkChunk      *LandmarkData;
RadarTrapChunk     *SpeedTrapData;
RoadblockInfoChunk *RoadblockData;

BSlotPool *PursuitSlotPool;
BSlotPool *CopSlotPool;
BSlotPool *SpikeStripSlotPool;

void (*gCopSpeechAllocateVoicesFn)(void);
void (*gCopSpeechFlushQueueFn)(void);
void (*gAICopDisableMyCarFn)(tCop *cop, int32_t b);

float fDisablingImpactMagnitudeTable[3] = { 40.0f, 60.0f, 75.0f };

typedef void (*DtorFn)(void *self, int32_t flags);

// ------------------------------------------------------ LoaderCops

#define COPS_CONTAINER   0x80034500u
#define COPS_SPEEDTRAPS  0x00034510u
#define COPS_ROADBLOCKS  0x00034520u
#define COPS_LANDMARKS   0x00034530u

// Both walk the container's children the same way; the unloader clears
// what the loader set. A container with no children leaves all three.
static int walk(uint8_t *c, int load)
{
    RadarTrapChunk     *traps = SpeedTrapData;
    LandmarkChunk      *land = LandmarkData;
    RoadblockInfoChunk *blocks = RoadblockData;
    uint8_t            *p, *end;

    if (bchunk_u32(c) != COPS_CONTAINER)
        return 0;
    p = c + 8;
    end = c + 8 + bchunk_u32(c + 4);
    if (p == end)
        return 1;
    do {
        uint32_t id = bchunk_u32(p);

        if (id == COPS_ROADBLOCKS)
            blocks = load ? (RoadblockInfoChunk *)(void *)(p + 8) : NULL;
        else if (id == COPS_SPEEDTRAPS)
            traps = load ? (RadarTrapChunk *)(void *)(p + 8) : NULL;
        else if (id == COPS_LANDMARKS)
            land = load ? (LandmarkChunk *)(void *)(p + 8) : NULL;
        p += 8 + bchunk_u32(p + 4);
    } while (p != end);
    RoadblockData = blocks;
    LandmarkData = land;
    SpeedTrapData = traps;
    return 1;
}

int copmgr_loader(uint8_t *c)
{
    return walk(c, 1);
}

int copmgr_unloader(uint8_t *c)
{
    return walk(c, 0);
}

// ------------------------------------------------------- the speakers

static int deque_empty(const CopSpeakerDeque *d)
{
    return d->Full == 0 && d->Tail == d->Head;
}

// Deque::PushHead, inlined into the constructor.
static void push_head(CopSpeakerDeque *d, uint32_t v)
{
    if (d->Full != 0)
        return;
    d->Head = d->Head == 0 ? 3 : d->Head - 1;
    d->Data[d->Head] = v;
    d->Full = d->Tail == d->Head;
}

uint32_t copmanager_get_current_cop_speaker(tCopManager *m)
{
    const CopSpeakerDeque *d = &m->CopSpeakers;

    return deque_empty(d) ? 0 : d->Data[d->Head];
}

uint32_t copmanager_reserve_cop_speaker(tCopManager *m)
{
    CopSpeakerDeque *d = &m->CopSpeakers;
    uint32_t         v;

    if (deque_empty(d))
        return 0;
    v = d->Data[d->Head];
    d->Head = d->Head + 1 == 4 ? 0 : d->Head + 1;
    d->Full = 0;
    return v;
}

void copmanager_release_cop_speaker(tCopManager *m, uint32_t v)
{
    CopSpeakerDeque *d = &m->CopSpeakers;

    if (d->Full != 0)
        return;
    d->Data[d->Tail] = v;
    d->Tail = d->Tail + 1 == 4 ? 0 : d->Tail + 1;
    d->Full = d->Tail == d->Head;
}

void copmanager_next_cop_speaker(tCopManager *m)
{
    if (!deque_empty(&m->CopSpeakers))
        copmanager_release_cop_speaker(m,
                                       copmanager_reserve_cop_speaker(m));
}

// ------------------------------------------------- the spots

void copmanager_init_road_block_structures(tCopManager *m)
{
    int32_t  forward = TheRaceParameters.TrackDirection == 0;
    int32_t  n = 0;
    uint32_t i;

    m->nNumRoadBlocks = 0;
    if (RoadblockData == NULL || TheRaceParameters.bRoadBlocks == 0)
        return;
    for (i = 0; i < RoadblockData->NumRoadblocks; i++) {
        const RoadblockInfo   *info = &RoadblockData->Roadblocks[i];
        uint32_t               dir = ROADBLOCKINFO_DIRECTION(info->Bits);
        NearestRoutePointInfo  nrpi;
        TopologyCoordinate     tc;
        TrackPathCoordinate    tpc;
        const TrackRoutePoint *pt;
        tRoadBlock            *rb;
        float                  along, lateral;

        m->RealRoadBlockIndexFromDataIndex[i] = -1;
        if (dir == 3 || (dir == 1 && !forward) || (dir == 2 && forward))
            continue;
        if (ai_get_nearest_route_point(&nrpi, &info->Centre,
                                       ALL_RACING_ROUTES, 0, 0.0f) == 0)
            continue;
        pt = nrpi.Point;
        rb = &m->RoadBlocks[n];
        rb->Route = nrpi.Route;
        rb->RoutePoint = nrpi.Point;
        rb->fRoadWidth = pt->LeftWidth + pt->RightWidth;
        if (rb->fRoadWidth < 9.0f)
            continue;
        topology_init(&tc);
        if (topology_has_topology(&tc, &info->Centre) == 0) {
            topology_destroy(&tc);
            continue;
        }
        rb->Name = info;
        rb->nSpikeSide = (int32_t)ROADBLOCKINFO_SPIKESIDE(info->Bits);
        rb->nIndexIntoLoadedData = (int32_t)i;
        rb->Flags = 0;
        rb->Difficulty = (int32_t)ROADBLOCKINFO_DIFFICULTY(info->Bits);
        if (ROADBLOCKINFO_CLOSURE(info->Bits) != 0)
            rb->Flags = 1;
        m->RealRoadBlockIndexFromDataIndex[i] = n;

        // The record's spot, brought onto the middle of the road.
        along = (info->Centre.x - pt->Position.x) * pt->Direction.x
              + (info->Centre.y - pt->Position.y) * pt->Direction.y;
        lateral = (pt->RightWidth - pt->LeftWidth) * 0.5f;
        trpoint_get_position2(pt, &rb->v2Position, along, lateral);
        rb->D.x = pt->Direction.x;
        rb->D.y = pt->Direction.y;
        rb->L.x = rb->D.y;
        rb->L.y = -rb->D.x;
        rb->aTrackMapIconAngle = (uint16_t)bATan(rb->L.x, rb->L.y);
        rb->cops[1] = NULL;
        rb->cops[0] = NULL;
        trackpath_coord_init_at(&tpc, &rb->v2Position);
        rb->fDistanceAroundTrack = tpc.DistanceAroundTrack;
        topology_destroy(&tc);
        n++;
    }
    m->nNumRoadBlocks = n;
}

void copmanager_init_speed_trap_structures(tCopManager *m)
{
    // Retail does not test the route search, and its result's slot on the
    // stack keeps the last trap's point when one misses.
    NearestRoutePointInfo nrpi = { NULL, NULL };
    uint32_t              i;

    m->nNumSpeedTraps = 0;
    if (SpeedTrapData == NULL || SpeedTrapData->NumRadarTraps == 0)
        return;
    for (i = 0; i < SpeedTrapData->NumRadarTraps; i++) {
        const RadarTrapInfo *info = &SpeedTrapData->Traps[i];
        TopologyCoordinate   tc;
        TrackPathCoordinate  tpc;
        tSpeedTrap          *t;
        bVector2             pos, dir;
        bPolar               polar;

        m->RealSpeedTrapIndexFromDataIndex[i] = -1;
        memcpy(&pos, &info->Centre, sizeof pos);
        topology_init(&tc);
        if (topology_has_topology(&tc, &pos) != 0) {
            trackpath_coord_init_at(&tpc, &pos);
            t = &m->SpeedTraps[m->nNumSpeedTraps];
            t->fDistanceAroundTrack = tpc.DistanceAroundTrack;
            t->Flags = 0;
            t->v2Position = info->Centre;
            t->cop = NULL;
            if (info->BeACopSpawnSpot != 0)
                t->Flags |= SPEEDTRAP_BEACOP;
            else if (info->BeACopReverseSpawnSpot != 0)
                t->Flags |= SPEEDTRAP_BEACOP_REVERSE;
            ai_get_nearest_route_point(&nrpi, &pos, ALL_RACING_ROUTES, 0,
                                       0.0f);
            if (nrpi.Point != NULL) {
                dir = nrpi.Point->Direction;
            } else {
                dir.x = 0.0f;
                dir.y = 0.0f;
            }
            bToPolar(&polar, &dir);
            m->RealSpeedTrapIndexFromDataIndex[i] = m->nNumSpeedTraps;
            m->nNumSpeedTraps++;
            t->Name = info;
            t->ang = polar.a;
        }
        topology_destroy(&tc);
    }
}

tRoadBlock *copmanager_get_road_block_from_loaded_data_index(tCopManager *m,
                                                             int32_t i)
{
    int32_t k = m->RealRoadBlockIndexFromDataIndex[i];

    return k == -1 ? NULL : &m->RoadBlocks[k];
}

tSpeedTrap *copmanager_get_speed_trap_from_loaded_data_index(tCopManager *m,
                                                             int32_t i)
{
    int32_t k = m->RealSpeedTrapIndexFromDataIndex[i];

    return k == -1 ? NULL : &m->SpeedTraps[k];
}

float copmanager_get_base_speed_trap_spawn_time(tCopManager *m)
{
    float laps = 1.0f, len, base = 45.0f;

    (void)m;
    if (TheRaceParameters.Point2Point == 0)
        laps = (float)TheRaceParameters.NumLapsInRace;
    len = laps * TheTrackPathManager.TrackLength;
    if (len < 15000.0f)
        base = 15.0f;
    else if (len < 30000.0f)
        base = 30.0f;
    if (TheRaceParameters.AIDemoMode != 0)
        return 1.0f;
    if (config_skip_fe() != 0)
        return SkipFETimeUntilCopsAppear;
    return base + world_random_f(pCurrentWorld, base);
}

Landmark *copmgr_find_landmark(const bVector2 *pos)
{
    uint32_t i;

    for (i = 0; i < LandmarkData->NumLandmarks; i++) {
        Landmark *l = &LandmarkData->LandmarkArray[i];

        if (is_point_in_poly(pos, l->VertsForArea, l->NumVerts) != 0)
            return l;
    }
    return NULL;
}

// ------------------------------------------------------- the pursuits

int32_t copmanager_find_free_pursuit_id(const tCopManager *m)
{
    int32_t i;

    for (i = 0; i < COPMANAGER_MAX_PURSUITS; i++)
        if (m->PursuitsById[i] == NULL)
            return i;
    return -1;
}

void copmanager_delete_pursuit(tCopManager *m, tPursuit *p)
{
    const VtEntry *e;

    if (p == NULL)
        return;
    p->Node.Prev->Next = p->Node.Next;
    p->Node.Next->Prev = p->Node.Prev;
    m->PursuitsById[p->nPursuitId] = NULL;
    e = vt_slot(p->vptr, TPURSUIT_VT_DTOR);
    ((DtorFn)e->fn)(vt_this(p, e), 3);
}

// ------------------------------------------------------ the impacts

tCop *copmanager_get_cop_by_car(tCopManager *m, struct Car *c)
{
    int32_t i;

    for (i = 0; i < m->nNumCops; i++)
        if (m->Cops[i]->pMyCar == c)
            return m->Cops[i];
    return NULL;
}

static float ee_min(float a, float b)
{
    return a < b ? a : b;
}

void copmanager_monitor_impact(tCopManager *m, struct Car *c, float amount,
                               int32_t twoCar)
{
    const RaceParameters *rp = &TheRaceParameters;
    int32_t               lvl = m->nDifficultyLevel;
    tCop                 *cop;

    if (rp->BeACop != 0) {
        // Retail's copy of a local table, by difficulty.
        static const float damageScale[3] = { 100.0f, 4.0f, 2.5f };
        tPursuit *pu;
        Car      *copCar;
        float     scale;
        int32_t   i;

        cop = copmanager_get_player_cop(m);
        if (cop == NULL || (pu = cop->pMyPursuit) == NULL)
            return;
        copCar = cop->pMyCar;
        if (pu->pChasedCar != c)
            return;
        if (rp->NumPlayerCars != 2) {
            float dx = copCar->State.Position.x - c->State.Position.x;
            float dy = copCar->State.Position.y - c->State.Position.y;

            if (!(sqrtf(dx * dx + dy * dy) < 50.0f))
                return;
        }
        if (!(5.0f <= amount))
            return;
        i = c->CarIndex;
        if (fDisablingImpactMagnitudeTable[lvl] <= amount) {
            m->fCarDamage[i] = 1.0f;
            return;
        }
        scale = damageScale[lvl] * 0.005f;
        if (rp->NumPlayerCars == 2)
            scale = 0.01f;
        m->fCarDamage[i] = ee_min(m->fCarDamage[i]
                                  + ee_min(amount * scale, 1.0f), 1.0f);
        return;
    }
    if (c->TheControlMode != COP_CONTROL)
        return;
    if (twoCar != 0)
        amount *= 1.5f;
    if (!(fDisablingImpactMagnitudeTable[lvl] <= amount))
        return;
    cop = copmanager_get_cop_by_car(m, c);
    if (cop == NULL)
        return;
    {
        const VtEntry *e = vt_slot(cop->vptr, TCOP_VT_IS_AI_CONTROLLED);

        if (((int32_t (*)(void *))e->fn)(vt_this(cop, e)) == 0)
            return;
    }
    if (((tAICopHead *)(void *)cop)->New32 <= 0.0f) {
        if (gAICopDisableMyCarFn == NULL) {
            fprintf(stderr, "copmanager_monitor_impact: "
                            "no tAICop::DisableMyCar\n");
            abort();
        }
        gAICopDisableMyCarFn(cop, 1);
    }
}

void copmgr_car_impact(tCopManager *m, struct CarCollisionBody *b,
                       float amount)
{
    CollisionBody *cb = &b->Dynamic.Body;
    int32_t        twoCar = 0, i = 0;

    if (!(1.0f <= amount))
        return;
    if (cb->NumCollisions > 0) {
        do {
            twoCar = collision_is_two_car_collision(
                collisionbody_get_collision(cb, i));
            i++;
        } while (i < cb->NumCollisions && twoCar == 0);
    }
    copmanager_monitor_impact(m, b->pCar, amount, twoCar);
}

// ------------------------------------------------- the manager itself

tCopManager *copmanager_construct(tCopManager *m)
{
    const RaceParameters *rp = &TheRaceParameters;
    int32_t               i;

    m->vptr = TCOPMANAGER_VTABLE;
    m->PursuitList.Next = m->PursuitList.Prev = &m->PursuitList;
    m->SpikeStripList.Next = m->SpikeStripList.Prev = &m->SpikeStripList;
    m->CopSpeakers.Head = 0;
    m->CopSpeakers.Tail = 0;
    m->CopSpeakers.Full = 0;
    PursuitSlotPool = bNewSlotPool(TPURSUIT_SLOT_SIZE, 6,
                                   "PursuitSlotPool", 16);
    CopSlotPool = bNewSlotPool(TAICOP_SLOT_SIZE, 6, "CopSlotPool", 16);
    SpikeStripSlotPool = bNewSlotPool(TSPIKESTRIP_SLOT_SIZE, 10,
                                      "SpikeStripSlotPool", 16);
    for (i = COPMANAGER_MAX_PURSUITS - 1; i >= 0; i--)
        m->PursuitsById[i] = NULL;
    m->New76 = NULL;
    m->bChopperBusy = 0;
    copmanager_init_road_block_structures(m);
    copmanager_init_speed_trap_structures(m);
    m->nNumAICops = 0;
    m->nPlayerCopIndex = -1;
    m->nNumCops = 0;
    for (i = 0; i < COPMANAGER_MAX_COPS; i++)
        m->Cops[i] = NULL;
    for (i = 0; i < 4; i++)
        push_head(&m->CopSpeakers, (uint32_t)i);
    m->TimeSinceLastSpeech = 0.0f;
    m->fSupervisorTimer = -50.0f;
    m->MaxSpeechGapTime = 12.0f;
    if (gCopSpeechAllocateVoicesFn != NULL)
        gCopSpeechAllocateVoicesFn();
    if (gCopSpeechFlushQueueFn != NULL)
        gCopSpeechFlushQueueFn();
    for (i = 0; i < COPMANAGER_NUM_PULLOVERS; i++) {
        tCarPulloverInfo *pl = &m->CarPullovers[i];

        // bShouldDisplayBustedText is left as it was.
        pl->bActive = 0;
        m->fPursuableTimer[i] = 0.0f;
        pl->bPlayNIS = 0;
        pl->bArrest = 0;
        pl->fHoldTimer = 0.0f;
        pl->nNumTickets = 0;
        pl->nCopIndex = -1;
    }
    for (i = 0; i < 8; i++)
        m->fSpeedTrapSpawnTimer[i] =
            copmanager_get_base_speed_trap_spawn_time(m);
    m->SpeechFillerCookie = 0;
    for (i = 0; i < COPMANAGER_NUM_CARS; i++)
        m->fCarDamage[i] = 0.0f;
    if (rp->BeACop != 0) {
        m->BeACopId = copmanager_reserve_cop_speaker(m);
        m->nBeACopNumRoadBlocks = rp->nNumBeACopRoadBlocks;
        m->nBeACopNumChopperAttacks = rp->nNumBeACopChoppers;
        m->fBeACopTime = (float)(int32_t)rp->TimeTrialTime.PackedTime
                       * 0.00025f;
    } else {
        m->fBeACopTime = 0.0f;
        m->nBeACopNumRoadBlocks = 0;
        m->nBeACopNumChopperAttacks = 0;
    }
    if (rp->CopStrength == 0)
        m->nDifficultyLevel = 0;
    else if (rp->CopStrength == 1)
        m->nDifficultyLevel = 1;
    else
        m->nDifficultyLevel = 2;
    m->bBeACopAlreadySaidLookOutForSpeeders = 0;
    m->New10488 = 0;
    m->nBeACopNumArrestsMade = 0;
    // InitRoadClosures, 0x00228ae0, is empty.
    m->New10500 = 0;
    m->fMaxCopCarXdim = 0.0f;
    m->fMaxCopCarYdim = 0.0f;
    return m;
}

void copmanager_destruct(tCopManager *m, int32_t flags)
{
    tPursuitNode *n;
    int32_t       i;

    m->vptr = TCOPMANAGER_VTABLE;
    if (m->New76 != NULL) {
        copmanager_delete_pursuit(m, m->New76);
        m->New76 = NULL;
    }
    while (m->PursuitList.Next != &m->PursuitList)
        copmanager_delete_pursuit(m, (tPursuit *)(void *)m->PursuitList.Next);
    for (i = 0; i < COPMANAGER_MAX_COPS; i++) {
        tCop *c = m->Cops[i];

        if (c != NULL) {
            const VtEntry *e = vt_slot(c->vptr, TCOP_VT_DTOR);

            ((DtorFn)e->fn)(vt_this(c, e), 3);
        }
    }
    while ((n = m->SpikeStripList.Next) != &m->SpikeStripList) {
        tSpikeStrip   *s = (tSpikeStrip *)(void *)n;
        const VtEntry *e;

        n->Prev->Next = n->Next;
        n->Next->Prev = n->Prev;
        e = vt_slot(s->vptr, TSPIKESTRIP_VT_DTOR);
        ((DtorFn)e->fn)(vt_this(s, e), 3);
    }
    bDeleteSlotPool(PursuitSlotPool);
    PursuitSlotPool = NULL;
    bDeleteSlotPool(CopSlotPool);
    CopSlotPool = NULL;
    bDeleteSlotPool(SpikeStripSlotPool);
    SpikeStripSlotPool = NULL;
    // The two lists' own destructors find them empty.
    if (flags & 1)
        bFree(m);
}

void copmgr_init_cops(void)
{
    if (TheRaceParameters.nMaxCops > 0)
        pCopManager = copmanager_construct(
            (tCopManager *)bMalloc((int)sizeof(tCopManager), "CopMgr", 0,
                                   16));
}

void copmgr_cleanup_cops(void)
{
    tCopManager *m = pCopManager;

    if (m != NULL) {
        const VtEntry *e = vt_slot(m->vptr, TCOPMANAGER_VT_DTOR);

        ((DtorFn)e->fn)(vt_this(m, e), 3);
        pCopManager = NULL;
    }
}

// ------------------------------------------------------ the table

static void dtor_entry(void *self, int32_t flags)
{
    copmanager_destruct((tCopManager *)self, flags);
}

static const VtEntry copmanager_vt[] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)dtor_entry },                 //   8  0x002239e8
};

void copmgr_install_vtables(void)
{
    vt_install(TCOPMANAGER_VTABLE, copmanager_vt,
               (int)(sizeof copmanager_vt / sizeof copmanager_vt[0]));
}
