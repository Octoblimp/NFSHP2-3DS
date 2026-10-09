// spikestrip -- see spikestrip.h.

#include "spikestrip.h"

#include <math.h>
#include <stddef.h>

#include "aicarcontroller.h"
#include "bchunk.h"
#include "bslotpool.h"
#include "car.h"
#include "carcontroller.h"
#include "copmgr.h"
#include "coputil.h"
#include "eefpu.h"
#include "emath.h"
#include "hudscore.h"
#include "playerzone.h"
#include "pursuit.h"
#include "race.h"
#include "realtime.h"
#include "topology.h"
#include "vtable.h"
#include "world.h"

typedef void (*DtorFn)(void *self, int32_t flags);
typedef void (*ForceBoostFn)(void *self, float f);

// 0x002bd238, by nDifficultyLevel: Be A Cop's ForceBoost for an AI racer
// on the strip. The image copies all three to the stack and indexes the
// copy, unchecked.
static const float BeACopSpikeBoost[3] = { 0.3f, 0.4f, 0.5f };

// ------------------------------------------------------ the belt pieces

tSpikeStripRenderElement *
tspikestriprenderelement_construct(tSpikeStripRenderElement *e)
{
    worldobject_construct(&e->Base, bchunk_hash("SPIKEBELT_00"), NULL, 0);
    e->vptr = TSPIKESTRIPRENDERELEMENT_VTABLE;
    return e;
}

void tspikestriprenderelement_destruct(tSpikeStripRenderElement *e,
                                       int32_t flags)
{
    e->vptr = TSPIKESTRIPRENDERELEMENT_VTABLE;
    worldobject_destruct(&e->Base, 0);
    if (flags & 1)
        bSlotFree(WorldObjectSlotPool, e);
}

// ------------------------------------------------------------ the strip

tSpikeStrip *tspikestrip_construct(tSpikeStrip *s, const bVector2 *a,
                                   const bVector2 *b, int32_t id,
                                   float lifetime)
{
    int32_t k;

    s->vptr = TSPIKESTRIP_VTABLE;
    for (k = 0; k < TSPIKESTRIP_MAX_ELEMENTS; k++)
        tspikestriprenderelement_construct(&s->Elements[k]);
    tspikestrip_init(s, a, b, id, lifetime);
    return s;
}

// `vopmula.xyz ACC,vfA,vfB` / `vopmsub.xyz vfA,vfB,vfA`: A cross B, each
// lane two rounded products and a rounded difference.
static void cross3(bVector3 *o, const bVector3 *a, const bVector3 *b)
{
    float x = a->y * b->z - b->y * a->z;
    float y = a->z * b->x - b->z * a->x;
    float z = a->x * b->y - b->x * a->y;

    o->x = x;
    o->y = y;
    o->z = z;
}

static void row(bVector4 *r, const bVector3 *v)
{
    r->x = v->x;
    r->y = v->y;
    r->z = v->z;
    r->w = 0.0f;
}

// The length is `sqrt.s` of the VU's sum, (x + y) + z, and the direction
// the VU's p1 - p0 times `div.s` 1 / length. The side is up x direction
// over `vrsqrt` of its own sum, Q added to 0 (`vaddq.x` from vf00). A belt
// whose ends meet on the road divides by zero the EE's way (FLT_MAX), so
// its direction is 0 and it has no pieces; the w lanes, which the image
// fills with whatever its stack held, reach nothing.
void tspikestrip_init(tSpikeStrip *s, const bVector2 *a, const bVector2 *b,
                      int32_t id, float lifetime)
{
    bVector3 p0, p1, dir, up, side, up2;
    bVector4 r0, r1, r2;
    float    dx, dy, dz, len, inv, q;
    int32_t  n, k;

    s->nRoadBlockID = id;
    s->v2Start = *a;
    s->v2End = *b;
    s->fLifetime = lifetime;
    get_vector_on_track(&p0, &s->v2Start);
    get_vector_on_track(&p1, &s->v2End);

    dx = p0.x - p1.x;
    dy = p0.y - p1.y;
    dz = p0.z - p1.z;
    len = sqrtf((dx * dx + dy * dy) + dz * dz);
    inv = ee_div(1.0f, len);
    dir.x = (p1.x - p0.x) * inv;
    dir.y = (p1.y - p0.y) * inv;
    dir.z = (p1.z - p0.z) * inv;
    n = ee_trunc_w(len * 1.5384616f);    // 0x3fc4ec4f, 20 / 13
    s->nNumElements = n;
    p0.x = p0.x + dir.x * 0.65f;
    p0.y = p0.y + dir.y * 0.65f;
    p0.z = p0.z + dir.z * 0.65f;
    if (!(n < 21))
        s->nNumElements = TSPIKESTRIP_MAX_ELEMENTS;

    up.x = 0.0f;
    up.y = 0.0f;
    up.z = 1.0f;
    cross3(&side, &up, &dir);
    q = 0.0f + ee_div(1.0f, sqrtf((side.x * side.x + side.y * side.y)
                                  + side.z * side.z));
    side.x = side.x * q;
    side.y = side.y * q;
    side.z = side.z * q;
    cross3(&up2, &dir, &side);
    row(&r0, &dir);
    row(&r1, &side);
    row(&r2, &up2);

    for (k = 0; k < s->nNumElements; k++) {
        WorldObject *o = &s->Elements[k].Base;

        o->Matrix.v0 = r0;
        o->Matrix.v1 = r1;
        o->Matrix.v2 = r2;
        o->Matrix.v3.x = p0.x;
        o->Matrix.v3.y = p0.y;
        o->Matrix.v3.z = p0.z;
        o->Matrix.v3.w = 1.0f;
        o->Enabled = 1;
        p0.x = p0.x + dir.x * 0.65f;
        p0.y = p0.y + dir.y * 0.65f;
        p0.z = p0.z + dir.z * 0.65f;
    }
}

// The count is read again on every pass. `sltiu v0,v0,1`: a piece is
// turned on exactly when its Enabled is 0.
int32_t tspikestrip_update(tSpikeStrip *s)
{
    int32_t done = 0;
    int32_t k;
    float   t;

    if (s->bIsBlinking != 0) {
        t = s->fBlinkTimer - WorldTimeElapsed;
        s->fBlinkTimer = t;
        if (t <= 0.0f)
            done = 1;
        for (k = 0; k < s->nNumElements; k++) {
            WorldObject *o = &s->Elements[k].Base;

            o->Enabled = o->Enabled == 0;
        }
        return done;
    }
    if (0.0f < s->fLifetime) {
        t = s->fLifetime - WorldTimeElapsed;
        s->fLifetime = t;
        if (t <= 0.0f)
            tspikestrip_blink_blink_poof(s);
    }
    return 0;
}

void tspikestrip_blink_blink_poof(tSpikeStrip *s)
{
    s->bIsBlinking = 1;
    s->fBlinkTimer = 2.0f;
}

// bTNode<tSpikeStrip>'s destructor, between the pieces and the free, is
// bNode's with 0 and does nothing.
void tspikestrip_destruct(tSpikeStrip *s, int32_t flags)
{
    int32_t k;

    s->vptr = TSPIKESTRIP_VTABLE;
    for (k = TSPIKESTRIP_MAX_ELEMENTS - 1; k >= 0; k--) {
        tSpikeStripRenderElement *e = &s->Elements[k];
        const VtEntry *v = vt_slot(e->vptr, TSPIKESTRIPRENDERELEMENT_VT_DTOR);

        ((DtorFn)v->fn)(vt_this(e, v), 0);
    }
    if (flags & 1)
        bSlotFree(SpikeStripSlotPool, s);
}

// ------------------------------------------------------ the cop manager

// The list's old head is read after the constructor.
void copmanager_add_spike_strip(tCopManager *m, const bVector2 *a,
                                const bVector2 *b, int32_t id, float t)
{
    tSpikeStrip  *s = (tSpikeStrip *)bSlotOMalloc(SpikeStripSlotPool);
    tPursuitNode *old;

    tspikestrip_construct(s, a, b, id, t);
    old = m->SpikeStripList.Next;
    m->SpikeStripList.Next = &s->Node;
    old->Prev = &s->Node;
    s->Node.Prev = &m->SpikeStripList;
    s->Node.Next = old;
}

static void create_pullover(tCopManager *m, Car *car)
{
    if (gCopManagerCreatePulloverFn != NULL)
        gCopManagerCreatePulloverFn(m, NULL, car, 0);
}

static void force_boost(CarController *ctl, float f)
{
    const VtEntry *e = vt_slot(ctl->_vtable, CARCONTROLLER_VT_FORCE_BOOST);

    ((ForceBoostFn)e->fn)(vt_this(ctl, e), f);
}

// After the tires are blown on a car that had none blown. The controller
// is read once; the player's cop and its player are read before the
// comparison, whichever way it goes.
static void react(tCopManager *m, Car *car)
{
    if (car->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER) {
        CarController *ctl = car->pCarController;

        if (TheRaceParameters.BeACop == 0) {
            aicarcontroller_force_pull_over((AICarController *)(void *)ctl,
                                            3.0f);
            force_boost(ctl, 0.4f);
        } else {
            force_boost(ctl, BeACopSpikeBoost[m->nDifficultyLevel]);
        }
    } else if (car->pPlayer != NULL && 20.0f < car->State.ForwardSpeed) {
        player_request_zone(car->pPlayer, PLAYER_ZONE_SLOMO_SHORT, 0, 1, 1);
    }

    if (TheRaceParameters.BeACop != 0) {
        Car           *copcar = m->Cops[m->nPlayerCopIndex]->pMyCar;
        struct Player *pl = copcar->pPlayer;

        if (car == copcar) {
            create_pullover(m, car);
            player_start_score(pl, SCORING_BLEW_YOUR_TIRES);
        } else if (car->pRacingCar != NULL
                   && copmanager_is_being_pursued(m, car) != NULL) {
            player_start_score(pl, SCORING_BLEW_THE_TIRES);
        }
    } else if ((car->pPlayer != NULL
                || car->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER)
               && copmanager_is_being_pursued(m, car) == NULL) {
        create_pullover(m, car);
    }
}

// One car against one strip, `start` and `d` the strip's start and its
// end less its start, `mid` the start plus half of that. pCurrentWorld is
// read once a car, for the table and the distance; WorldTimeElapsed once
// for both lanes. The body's matrix is its three rows and the position,
// all four lanes, with the position's w then 1.
static void monitor_car(tCopManager *m, int32_t i, const bVector2 *start,
                        const bVector2 *d, const bVector2 *mid)
{
    World         *w = pCurrentWorld;
    Car           *car = w->CarTable[i];
    const bVector3 *pos = &car->State.Position;
    bMatrix4       body, r;
    bVector2       mv, p;
    float          dx, dy, wte;
    int32_t        bits, k, old;

    if (!(world_get_distance_to_closest_player_2d(
              w, (const bVector2 *)(const void *)pos) < 250.0f))
        return;
    if (car_is_blinking(car))
        return;
    dx = mid->x - pos->x;
    dy = mid->y - pos->y;
    if (!(sqrtf(dx * dx + dy * dy) < 40.0f))
        return;

    wte = WorldTimeElapsed;
    mv.x = car->State.Velocity.x * wte;
    mv.y = car->State.Velocity.y * wte;
    body.v0 = car->State.BodyMatrix.v0;
    body.v1 = car->State.BodyMatrix.v1;
    body.v2 = car->State.BodyMatrix.v2;
    body.v3.x = pos->x;
    body.v3.y = pos->y;
    body.v3.z = pos->z;
    body.v3.w = 1.0f;
    bits = 0;
    for (k = 0; k < 4; k++) {
        if (car->State.WheelTouchingGround[k] == 0)
            continue;
        eMulMatrix(&r, &car->State.WheelMatrix[k], &body);
        p.x = r.v3.x;
        p.y = r.v3.y;
        if (do_segments_intersect(&p, &mv, start, d))
            bits |= 1 << k;
    }
    if ((car->BlownTireBits & bits) == bits)
        return;
    old = (int8_t)car->NumBlownTires;
    car_trigger_tire_blow_out(car, bits);
    if (old != 0)
        return;
    react(m, car);
}

// The next strip is read before Update; the one that is done is unlinked
// by its own links, read again.
void copmanager_monitor_spike_belts(tCopManager *m)
{
    tPursuitNode *list = &m->SpikeStripList;
    tPursuitNode *n, *next;
    int32_t       ncars = pCurrentWorld->TotalNumCars;

    for (n = list->Next; n != list; n = next) {
        tSpikeStrip *s = (tSpikeStrip *)(void *)n;
        bVector2     start, d, mid;
        int32_t      i;

        next = n->Next;
        if (tspikestrip_update(s)) {
            tPursuitNode  *nx = n->Next, *pv = n->Prev;
            const VtEntry *v;

            pv->Next = nx;
            nx->Prev = pv;
            v = vt_slot(s->vptr, TSPIKESTRIP_VT_DTOR);
            ((DtorFn)v->fn)(vt_this(s, v), 3);
            continue;
        }
        start = s->v2Start;
        d.x = s->v2End.x - s->v2Start.x;
        d.y = s->v2End.y - s->v2Start.y;
        mid.x = start.x + d.x * 0.5f;
        mid.y = start.y + d.y * 0.5f;
        for (i = 0; i < ncars; i++)
            monitor_car(m, i, &start, &d, &mid);
    }
}

// ----------------------------------------------------------- the tables

static void tspikestrip_dtor_entry(void *self, int32_t flags)
{
    tspikestrip_destruct((tSpikeStrip *)self, flags);
}

static void tspikestriprenderelement_dtor_entry(void *self, int32_t flags)
{
    tspikestriprenderelement_destruct((tSpikeStripRenderElement *)self,
                                      flags);
}

static const VtEntry tspikestrip_vt[] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)tspikestrip_dtor_entry },               // 8  0x00241430
};

static const VtEntry tspikestriprenderelement_vt[] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)tspikestriprenderelement_dtor_entry },  // 8  0x00241a48
};

void spikestrip_install_vtables(void)
{
    vt_install(TSPIKESTRIP_VTABLE, tspikestrip_vt,
               (int)(sizeof tspikestrip_vt / sizeof tspikestrip_vt[0]));
    vt_install(TSPIKESTRIPRENDERELEMENT_VTABLE, tspikestriprenderelement_vt,
               (int)(sizeof tspikestriprenderelement_vt
                     / sizeof tspikestriprenderelement_vt[0]));
}
