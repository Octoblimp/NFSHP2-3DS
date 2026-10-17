// munition -- see munition.h.

#include "munition.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "acidsys.h"
#include "airoute.h"
#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "bplist.h"
#include "bvector.h"
#include "car.h"
#include "collision.h"
#include "collisionsound.h"
#include "cop.h"
#include "copmanager.h"
#include "coputil.h"
#include "eefpu.h"
#include "emath.h"
#include "psychodriver.h"
#include "pursuit.h"
#include "race.h"
#include "rigidbody.h"
#include "sundraw.h"
#include "topology.h"
#include "vtable.h"
#include "world.h"

BSlotPool *RocketSlotPool;
BSlotPool *SmokeBombSlotPool;
BSlotPool *DroppedSpikesSlotPool;

bNode RocketEmitters        = { &RocketEmitters, &RocketEmitters };
bNode SmokeBombEmitters     = { &SmokeBombEmitters, &SmokeBombEmitters };
bNode DroppedSpikesEmitters = { &DroppedSpikesEmitters,
                                &DroppedSpikesEmitters };

MunitionEffectsHandler *TheMunitionEffectsHandler;

const ExplodeParams SmokeBombExplodeParams     = { 25, 10, 10, 5, 3, 6, 1 };
const ExplodeParams DroppedSpikesExplodeParams = { 1, 0, 10, 5, 2, 8, 0 };
const ExplodeParams RocketExplodeParams        = { 20, 20, 10, 8, 0, 6, 0 };

// gp-28852 and gp-28848: how much of MaxStrength stops a car, and how
// high a rocket flies over the ground.
#define MUNITION_STOP_SHARE   0.8f
#define ROCKET_HEIGHT         0.9f

// 0x3bb40000: a BAM in degrees.
#define BAM_TO_DEGREES        0.0054931640625f

// The e-brake stop a hard hit gives, in seconds (0x40600000).
#define MUNITION_EBRAKE_TIME  3.5f

typedef void      (*VtDestroyFn)(void *self, int32_t flags);
typedef bVector3 *(*VtVectorFn)(void *self);
typedef void      (*VtVoidFn)(void *self);
typedef void      (*VtPhysicsModeFn)(void *self, CollisionBody *other);
typedef void      (*VtImpulseFn)(void *self, bVector3 *j, bVector3 *at);

static void body_destroy(void *b, int32_t flags)
{
    const VtEntry *e = vt_slot(((CollisionBody *)b)->_vtable,
                               COLLISIONBODY_VT_DESTROY);

    ((VtDestroyFn)e->fn)(vt_this(b, e), flags);
}

static bVector3 *body_vector(void *b, int slot)
{
    const VtEntry *e = vt_slot(((CollisionBody *)b)->_vtable, slot);

    return ((VtVectorFn)e->fn)(vt_this(b, e));
}

static void body_on_lifetime_end(void *b)
{
    const VtEntry *e = vt_slot(((CollisionBody *)b)->_vtable,
                               SMOKEABLE_VT_ON_LIFETIME_END);

    ((VtVoidFn)e->fn)(vt_this(b, e));
}

static void set_tables(Munition *m, uint32_t main_vt, uint32_t system_vt)
{
    m->Base.System._vtable = system_vt;
    m->Base.Dynamic.Body._vtable = main_vt;
}

static float min_s(float fs, float ft)
{
    return ft < fs ? ft : fs;
}

static float max_s(float fs, float ft)
{
    return fs < ft ? ft : fs;
}

// `(int)(deg * 65536) / 360`, a heading in degrees as a BAM.
static uint16_t degrees_to_bam(float deg)
{
    return (uint16_t)(ee_trunc_w(deg * 65536.0f) / 360);
}

static void unported(const char *name)
{
    fprintf(stderr, "munition: %s is not ported\n", name);
    abort();
}

// ------------------------------------------------------------ the module

// InitSmokeBomb (0x001bec98), InitRocket (0x001bf448) and
// InitDroppedSpikes (0x001beff0).
static void init_smoke_bomb(void)
{
    SmokeBombSlotPool = bNewSlotPool((int)sizeof(SmokeBomb), 14,
                                     "SmokeBombSlotPool", 16);
    smokeable_register_creator(ST_SMOKEBOMB, smokebomb_smokeable_creator);
    afx_get_emitters(&SmokeBombEmitters, bchunk_hash("SMOKEBOMBEXPLD"));
}

static void init_rocket(void)
{
    RocketSlotPool = bNewSlotPool((int)sizeof(Rocket), 3, "RocketSlotPool",
                                  16);
    smokeable_register_creator(ST_ROCKET, rocket_smokeable_creator);
    afx_get_emitters(&RocketEmitters, bchunk_hash("ROCKETEXPLD"));
}

static void init_dropped_spikes(void)
{
    DroppedSpikesSlotPool = bNewSlotPool((int)sizeof(DroppedSpikes), 8,
                                         "DroppedSpikesSlotPool", 16);
    smokeable_register_creator(ST_DROPPED_SPIKES,
                               droppedspikes_smokeable_creator);
    afx_get_emitters(&DroppedSpikesEmitters, bchunk_hash("ROCKETEXPLD"));
}

// The Fini three: 0x001becf0, 0x001bf4a0 and 0x001bf048.
static void fini_class(BSlotPool **pool, bNode *emitters)
{
    if (*pool != NULL) {
        bDeleteSlotPool(*pool);
        *pool = NULL;
    }
    afx_delete_emitters(emitters);
}

// The image asks bMalloc for 8 bytes; the host's handler is wider.
void init_munitions(void)
{
    MunitionEffectsHandler *h = (MunitionEffectsHandler *)bMalloc(
        (int)sizeof(MunitionEffectsHandler), "MunitionEffectsHandler", 0,
        16);

    TheMunitionEffectsHandler = h;
    h->List.next = &h->List;
    h->List.prev = &h->List;
    init_smoke_bomb();
    init_rocket();
    init_dropped_spikes();
}

void close_munitions(void)
{
    fini_class(&SmokeBombSlotPool, &SmokeBombEmitters);
    fini_class(&RocketSlotPool, &RocketEmitters);
    fini_class(&DroppedSpikesSlotPool, &DroppedSpikesEmitters);
    if (TheMunitionEffectsHandler != NULL)
        munitioneffectshandler_destroy(TheMunitionEffectsHandler, 3);
    TheMunitionEffectsHandler = NULL;
}

// Init__6Rocket and Init__9SmokeBomb are empty; Init__13DroppedSpikes
// (0x001bef88) clears DeploySpikes.
Smokeable *rocket_smokeable_creator(int32_t id, SmokeableInfo *info,
                                    uint32_t name_hash)
{
    Rocket *r = (Rocket *)bSlotOMalloc(RocketSlotPool);

    munition_init(&r->Base, id, info, name_hash);
    set_tables(&r->Base, ROCKET_VTABLE, ROCKET_SYSTEM_VTABLE);
    return &r->Base.Base;
}

Smokeable *smokebomb_smokeable_creator(int32_t id, SmokeableInfo *info,
                                       uint32_t name_hash)
{
    SmokeBomb *b = (SmokeBomb *)bSlotOMalloc(SmokeBombSlotPool);

    droppedbomb_init(b, id, info, name_hash);
    set_tables(b, SMOKEBOMB_VTABLE, SMOKEBOMB_SYSTEM_VTABLE);
    return &b->Base;
}

Smokeable *droppedspikes_smokeable_creator(int32_t id, SmokeableInfo *info,
                                           uint32_t name_hash)
{
    DroppedSpikes *s = (DroppedSpikes *)bSlotOMalloc(DroppedSpikesSlotPool);

    droppedbomb_init(&s->Base, id, info, name_hash);
    set_tables(&s->Base, DROPPEDSPIKES_VTABLE, DROPPEDSPIKES_SYSTEM_VTABLE);
    s->DeploySpikes = 0;
    return &s->Base.Base;
}

// ---------------------------------------------------------- Munition

Munition *munition_init(Munition *m, int32_t id, SmokeableInfo *info,
                        uint32_t name_hash)
{
    smokeable_init(&m->Base, id, info, name_hash);
    set_tables(m, MUNITION_VTABLE, MUNITION_SYSTEM_VTABLE);
    m->BackupDone = 0;
    return m;
}

// Bit 0 of `flags` frees the slot to SmokeableSlotPool
// (__dl__9Smokeable), as for a plain smokeable; every class below passes
// 0 and frees to its own pool.
void munition_destroy(Munition *m, int32_t flags)
{
    set_tables(m, MUNITION_VTABLE, MUNITION_SYSTEM_VTABLE);
    smokeable_destroy(&m->Base, 0);
    if (flags & 1)
        bSlotFree(SmokeableSlotPool, m);
}

// The distance is in x and y only, and so is the push, until a car on its
// wheels is given CoordZAdjust up as well; the push's point is ArmZAdjust
// above the car's centre (its w lane is the stack's in the image, 0
// here). Each car's body is put into physics mode first. Only a player's
// car gets the glare (a rocket's, in a one-player race), and the hard
// hit: CarDamage's wreck, an e-brake stop for a real driver, and the
// slow-motion camera for a car still racing when the class asks for it.
// An AI car on physics or mellow movement is e-braked whatever the
// strength.
void munition_explode_warhead(Munition *m, const ExplodeParams *p,
                              MunitionsType type)
{
    bVector3 at, dir;
    int32_t  i;

    at.x = 0.0f;
    at.y = 0.0f;
    at.z = p->ArmZAdjust;
    at.pad = 0.0f;
    for (i = 0; i < pCurrentWorld->TotalNumCars; i++) {
        struct Car     *car = pCurrentWorld->CarTable[i];
        const bVector3 *pos;
        CollisionBody  *body;
        const VtEntry  *e;
        float           dx, dy, dist, s;

        if (car->TheMovementMode == eNO_MOVEMENT)
            continue;
        pos = body_vector(m, COLLISIONBODY_VT_GET_POSITION);
        dx = car->State.Position.x - pos->x;
        dy = car->State.Position.y - pos->y;
        dist = sqrtf(dx * dx + dy * dy);
        if (!(dist < p->MaxRange))
            continue;
        pos = body_vector(m, COLLISIONBODY_VT_GET_POSITION);
        dir.x = car->State.Position.x - pos->x;
        dir.y = car->State.Position.y - pos->y;
        dir.z = 0.0f;
        dir.pad = car->State.Position.pad - pos->pad;
        if (dist < p->MinRange)
            s = p->MaxStrength;
        else
            s = p->MinStrength
                + (p->MaxStrength - p->MinStrength) * (p->MaxRange - dist)
                      / (p->MaxRange - p->MinRange);
        bNormalize3To(&dir, &dir, s);
        if (car->State.nWheelsTouchingGround > 0)
            dir.z = dir.z + p->CoordZAdjust;
        body = (CollisionBody *)(void *)car->pDynamicCollisionBody;
        e = vt_slot(body->_vtable, COLLISIONBODY_VT_SET_TO_PHYSICS_MODE);
        ((VtPhysicsModeFn)e->fn)(vt_this(body, e), NULL);
        e = vt_slot(body->_vtable, COLLISIONBODY_VT_APPLY_IMPULSE);
        ((VtImpulseFn)e->fn)(vt_this(body, e), &dir, &at);
        if (car->pPlayer != NULL) {
            if (type == MT_BANG_FLASH && TheRaceParameters.NumPlayerCars == 1)
                bStartGlare = 1;
            if (!(p->MaxStrength * MUNITION_STOP_SHARE < s))
                continue;
            if (car->pCarDamage != NULL) {
                if (gCarDamageWreckFn == NULL)
                    unported("CarDamage's wreck (0x001b5bc8)");
                gCarDamageWreckFn(car->pCarDamage);
            }
            if (car->TheControlMode == REAL_CONTROL
                && gRealDriverForceEBrakeStopFn != NULL)
                gRealDriverForceEBrakeStopFn(
                    (struct RealDriver *)(void *)car->pCarDriver,
                    MUNITION_EBRAKE_TIME);
            if (p->bRequestZoneCamera != 0
                && car->pRacingCar->FinishReason == 0
                && gPlayerRequestZoneFn != NULL)
                gPlayerRequestZoneFn(car->pPlayer, 1, 0, 1, 1);
        } else if (car->TheControlMode == AI_CONTROL
                   && (car->TheMovementMode == PHYSICS_MOVEMENT
                       || car->TheMovementMode == MELLOW_MOVEMENT)) {
            ((PsychoDriver *)(void *)car->pCarDriver)->EBrakeTimer =
                MUNITION_EBRAKE_TIME;
        }
    }
    collision_sound_play_explosion(
        body_vector(m, COLLISIONBODY_VT_GET_POSITION));
}

void munition_launch(Munition *m, const bMatrix4 *mat, const bVector3 *v)
{
    smokeable_set_initial_position(&m->Base, mat, v);
    smokeable_awaken(&m->Base);
    smokeable_activate_anchor_emitters(&m->Base);
}

void munition_get_flat_matrix(Munition *m, bMatrix4 *out)
{
    const bVector3 *p;

    bIdentity(out);
    p = body_vector(m, COLLISIONBODY_VT_GET_POSITION);
    out->v3.x = p->x;
    out->v3.y = p->y;
    out->v3.z = p->z;
    out->v3.w = 1.0f;
}

void munition_backup(CollisionBody *b, float t)
{
    ((Munition *)(void *)b)->BackupDone = 1;
    dynamiccollisionbody_backup(b, t);
}

// The explosion common to the three OnLifetimeEnds: nothing with no
// handler.
static int32_t explode(Munition *m, bNode *emitters, const ExplodeParams *p,
                       MunitionsType type)
{
    bMatrix4 mat;

    if (TheMunitionEffectsHandler == NULL)
        return 0;
    munition_get_flat_matrix(m, &mat);
    munitioneffectshandler_add_effect(TheMunitionEffectsHandler, emitters,
                                      &mat);
    munition_explode_warhead(m, p, type);
    return 1;
}

// ------------------------------------------------------- DroppedBomb

Munition *droppedbomb_init(Munition *m, int32_t id, SmokeableInfo *info,
                           uint32_t name_hash)
{
    munition_init(m, id, info, name_hash);
    set_tables(m, DROPPEDBOMB_VTABLE, DROPPEDBOMB_SYSTEM_VTABLE);
    return m;
}

void droppedbomb_destroy(Munition *m, int32_t flags)
{
    set_tables(m, DROPPEDBOMB_VTABLE, DROPPEDBOMB_SYSTEM_VTABLE);
    munition_destroy(m, 0);
    if (flags & 1)
        bSlotFree(SmokeableSlotPool, m);
}

void droppedbomb_move(CollisionBody *b, float dt)
{
    smokeable_move(b, dt);
}

void droppedbomb_launch(Munition *m, const bMatrix4 *mat, const bVector3 *v)
{
    munition_launch(m, mat, v);
}

// --------------------------------------------------------- SmokeBomb

SmokeBomb *smokebomb_new(SmokeBomb *b)
{
    int32_t        id = collisionbody_get_next_id();
    SmokeableInfo *info = find_smokeable_info(bchunk_hash("CS_SMOKEBOMB"));

    droppedbomb_init(b, id, info, bchunk_hash("SMOKEBOMB"));
    set_tables(b, SMOKEBOMB_VTABLE, SMOKEBOMB_SYSTEM_VTABLE);
    return b;
}

void smokebomb_destroy(SmokeBomb *b, int32_t flags)
{
    set_tables(b, SMOKEBOMB_VTABLE, SMOKEBOMB_SYSTEM_VTABLE);
    droppedbomb_destroy(b, 0);
    if (flags & 1)
        bSlotFree(SmokeBombSlotPool, b);
}

void smokebomb_on_lifetime_end(CollisionBody *b)
{
    explode((Munition *)(void *)b, &SmokeBombEmitters,
            &SmokeBombExplodeParams, MT_SMOKE_BOMB);
}

// The first of this step's collisions with a car sets it off, with the
// smokeable crash sound when the collision made none of its own.
void smokebomb_move(CollisionBody *b, float dt)
{
    Munition *m = (Munition *)(void *)b;

    if (m->BackupDone == 0) {
        struct Car *c1 = NULL, *c2 = NULL;
        int32_t     i;

        for (i = 0; i < b->NumCollisions; i++) {
            Collision *c = collisionbody_get_collision(b, i);

            collision_get_colliding_cars(c, &c1, &c2);
            if (c1 == NULL && c2 == NULL)
                continue;
            if (c->Sample == NULL)
                collision_sound_play_smokeable(&c->InitialContactPoint, NULL);
            body_on_lifetime_end(m);
            body_destroy(m, 3);
            return;
        }
    }
    m->BackupDone = 0;
    droppedbomb_move(b, dt);
}

int32_t smokebomb_get_smoke_type(CollisionBody *b)
{
    (void)b;
    return ST_SMOKEBOMB;
}

// ----------------------------------------------------- DroppedSpikes

DroppedSpikes *droppedspikes_new(DroppedSpikes *s)
{
    int32_t        id = collisionbody_get_next_id();
    SmokeableInfo *info = find_smokeable_info(bchunk_hash("CS_SMOKEBOMB"));

    droppedbomb_init(&s->Base, id, info, bchunk_hash("SMOKEBOMB"));
    set_tables(&s->Base, DROPPEDSPIKES_VTABLE, DROPPEDSPIKES_SYSTEM_VTABLE);
    s->DeploySpikes = 0;
    return s;
}

void droppedspikes_destroy(DroppedSpikes *s, int32_t flags)
{
    set_tables(&s->Base, DROPPEDSPIKES_VTABLE, DROPPEDSPIKES_SYSTEM_VTABLE);
    droppedbomb_destroy(&s->Base, 0);
    if (flags & 1)
        bSlotFree(DroppedSpikesSlotPool, s);
}

void droppedspikes_on_lifetime_end(CollisionBody *b)
{
    DroppedSpikes *s = (DroppedSpikes *)(void *)b;

    if (explode(&s->Base, &DroppedSpikesEmitters,
                &DroppedSpikesExplodeParams, MT_SPIKE_BOMB))
        droppedspikes_make_spike_belt(s);
}

void droppedspikes_move(CollisionBody *b, float dt)
{
    DroppedSpikes *s = (DroppedSpikes *)(void *)b;

    if (s->Base.BackupDone == 0 && s->DeploySpikes != 0) {
        body_on_lifetime_end(s);
        body_destroy(s, 3);
        return;
    }
    s->Base.BackupDone = 0;
    droppedbomb_move(b, dt);
}

// The impulse is taken whole and never applied: the spikes stop where
// they land.
float droppedspikes_consider_impulse(CollisionBody *b, bVector3 *j,
                                     bVector3 *at)
{
    (void)j;
    (void)at;
    ((DroppedSpikes *)(void *)b)->DeploySpikes = 1;
    return 1.0f;
}

void droppedspikes_apply_impulse(CollisionBody *b, bVector3 *j, bVector3 *at)
{
    (void)j;
    (void)at;
    ((DroppedSpikes *)(void *)b)->DeploySpikes = 1;
}

// `side` is the spikes' offset across the route point's direction,
// positive to its right; `w` how far inside that side's edge they are.
// The strip runs from 2 (or to the edge, if nearer) on the left of the
// direction to 2 (or the edge) on its right, given the
// image's id -1 and 20 seconds.
void droppedspikes_make_spike_belt(DroppedSpikes *s)
{
    const bVector3        *pos;
    NearestRoutePointInfo  info;
    const TrackRoutePoint *pt;
    bVector2               dir, p1, p2;
    int32_t                found;
    float                  elev, side, w, a, b;

    pos = body_vector(s, COLLISIONBODY_VT_GET_POSITION);
    elev = topology_get_elevation(&s->Base.Base.TC, pos, NULL, NULL, &found);
    if (found == 0 || 1.0f < pos->z - elev)
        return;
    if (!ai_get_nearest_route_point(&info, (const bVector2 *)(const void *)pos,
                                    ALL_RACING_ROUTES, 2, 0.0f))
        return;
    pt = info.Point;
    side = (pos->x - pt->Position.x) * pt->Direction.y
           - (pos->y - pt->Position.y) * pt->Direction.x;
    if (0.0f < side)
        w = side - pt->RightWidth;
    else
        w = -(side + pt->LeftWidth);
    w = -w;
    if (w < 0.0f)
        return;
    dir.x = pt->Direction.y;
    dir.y = -pt->Direction.x;
    if (0.0f < side) {
        a = min_s(w, 2.0f);
        b = 2.0f;
    } else {
        a = 2.0f;
        b = min_s(w, 2.0f);
    }
    bScaleAdd2(&p1, (const bVector2 *)(const void *)pos, &dir, a);
    bScaleAdd2(&p2, (const bVector2 *)(const void *)pos, &dir, -b);
    if (gCopManagerAddSpikeStripFn != NULL)
        gCopManagerAddSpikeStripFn(pCopManager, &p2, &p1, -1, 20.0f);
}

int32_t droppedspikes_get_smoke_type(CollisionBody *b)
{
    (void)b;
    return ST_DROPPED_SPIKES;
}

// ------------------------------------------------------------ Rocket

Rocket *rocket_new(Rocket *r)
{
    int32_t        id = collisionbody_get_next_id();
    SmokeableInfo *info = find_smokeable_info(bchunk_hash("CS_Rocket"));

    munition_init(&r->Base, id, info, bchunk_hash("ROCKET"));
    set_tables(&r->Base, ROCKET_VTABLE, ROCKET_SYSTEM_VTABLE);
    return r;
}

void rocket_destroy(Rocket *r, int32_t flags)
{
    set_tables(&r->Base, ROCKET_VTABLE, ROCKET_SYSTEM_VTABLE);
    munition_destroy(&r->Base, 0);
    if (flags & 1)
        bSlotFree(RocketSlotPool, r);
}

void rocket_on_lifetime_end(CollisionBody *b)
{
    explode((Munition *)(void *)b, &RocketEmitters, &RocketExplodeParams,
            MT_BANG_FLASH);
}

void rocket_launch(Rocket *r, const bMatrix4 *mat, const bVector3 *v,
                   struct Car *target)
{
    float yaw;

    munition_launch(&r->Base, mat, v);
    yaw = make_relative_angle((float)bATan(v->x, v->y) * BAM_TO_DEGREES);
    r->Target = target;
    r->Yaw = yaw;
}

// The rocket is flown, not simulated: after BeginMove its yaw turns
// toward the target by at most 90 degrees a second, and its velocity is
// set to 30 along the yaw with a climb of twelve times the height it is
// short of (0.9 over the ground below it), within 25 either way. The
// body's state is set to the position a step on, turned by the climb and
// the yaw, with the velocity as SetState's momentum argument (which
// multiplies it by the mass; the image works out velocity times mass on
// the side, and drops it). Then the drawn matrix, the emitters and the
// timers, as Smokeable::Move ends.
void rocket_move(CollisionBody *b, float dt)
{
    Rocket         *r = (Rocket *)(void *)b;
    Smokeable      *s = &r->Base.Base;
    bVector4        np, zero;
    bVector3        d;
    bVector3       *vel;
    const bVector3 *pos;
    bMatrix4        m;
    int32_t         terrain;
    float           elev, ang, turn, lim;

    zero.x = 0.0f;
    zero.y = 0.0f;
    zero.z = 0.0f;
    zero.w = 0.0f;
    if (r->Base.BackupDone != 0) {
        r->Base.BackupDone = 0;
        return;
    }
    if (r->Target == NULL) {
        body_on_lifetime_end(r);
        body_destroy(r, 3);
        return;
    }
    dynamiccollisionbody_begin_move(&s->Dynamic, dt);
    pos = body_vector(r, COLLISIONBODY_VT_GET_POSITION);
    elev = topology_get_elevation(&s->TC, pos, &terrain, NULL, NULL);
    d.x = r->Target->State.Position.x - pos->x;
    d.y = r->Target->State.Position.y - pos->y;
    elev = elev + ROCKET_HEIGHT;
    ang = make_relative_angle((float)bATan(d.x, d.y) * BAM_TO_DEGREES);
    lim = dt * 90.0f;
    turn = make_relative_angle(ang - r->Yaw);
    turn = min_s(lim, max_s(turn, -lim));
    r->Yaw = r->Yaw + turn;
    vel = body_vector(r, COLLISIONBODY_VT_GET_VELOCITY);
    vel->x = bCosBam(degrees_to_bam(-r->Yaw)) * 30.0f;
    vel->y = -bSinBam(degrees_to_bam(-r->Yaw)) * 30.0f;
    vel->z = min_s(25.0f, max_s((elev - pos->z) * 12.0f, -25.0f));
    np.x = vel->x * dt + pos->x;
    np.y = vel->y * dt + pos->y;
    np.z = vel->z * dt + pos->z;
    np.w = vel->pad * dt + pos->pad;
    bIdentity(&m);
    eRotateY(&m, &m, (uint16_t)bATan(vel->z, 30.0f));
    eRotateZ(&m, &m, degrees_to_bam(r->Yaw));
    rigidbody_set_state((RigidBody *)s->Dynamic.pBody, &np, &m,
                        (const bVector4 *)(const void *)vel, &zero);
    m.v3.x = np.x;
    m.v3.y = np.y;
    m.v3.z = np.z;
    s->TheWorldObject.Matrix = m;
    s->TheWorldObject.Enabled = 1;
    smokeable_position_changed(s);
    smokeable_service_emitters(s, &m);
    smokeable_check_timers(s);
}

// Struck: the target is dropped, so the next Move sets it off. The
// returned share is the image's, a large negative.
float rocket_consider_impulse(CollisionBody *b, bVector3 *j, bVector3 *at)
{
    (void)j;
    (void)at;
    ((Rocket *)(void *)b)->Target = NULL;
    return -57575.0f;
}

void rocket_apply_impulse(CollisionBody *b, bVector3 *j, bVector3 *at)
{
    (void)j;
    (void)at;
    ((Rocket *)(void *)b)->Target = NULL;
}

int32_t rocket_get_smoke_type(CollisionBody *b)
{
    (void)b;
    return ST_ROCKET;
}

// --------------------------------------------- MunitionEffectsHandler

static AcidEmitter *node_emitter(const bNode *n)
{
    return (AcidEmitter *)((const bPNode *)(const void *)n)->Object;
}

// bPList's RemoveHead and Remove: the node off the list and freed.
static void remove_node(bNode *n)
{
    n->prev->next = n->next;
    n->next->prev = n->prev;
    bpnode_free(n);
}

static void drop_emitter(AcidEmitter *e)
{
    acid_system_remove_auto_emitter(&WorldEffects, e);
    if (e != NULL)
        acid_emitter_delete(e, 3);
}

void munitioneffectshandler_destroy(MunitionEffectsHandler *h, int32_t flags)
{
    while (h->List.next != &h->List) {
        bNode       *n = h->List.next;
        AcidEmitter *e = node_emitter(n);

        remove_node(n);
        drop_emitter(e);
    }
    if (flags & 1)
        bFree(h);
}

void munitioneffectshandler_do_timestep(MunitionEffectsHandler *h, float dt)
{
    bNode *n, *next;

    (void)dt;
    for (n = h->List.next; n != &h->List; n = next) {
        AcidEmitter *e = node_emitter(n);

        next = n->next;
        if (e->State == ACID_ON)
            continue;
        remove_node(n);
        drop_emitter(e);
    }
}

void munitioneffectshandler_add_effect(MunitionEffectsHandler *h,
                                       bNode *list, const bMatrix4 *m)
{
    bNode *n;

    for (n = list->next; n != list; n = n->next) {
        AcidEmitter *c = afx_copy_emitter((const AcidEmitter *)(void *)n);
        bPNode      *p;
        bNode       *head;

        if (c == NULL)
            continue;
        c->State = ACID_ON;
        c->LocalWorld = *m;
        acid_system_add_auto_emitter(&WorldEffects, c);
        p = bpnode_malloc();
        head = h->List.next;
        h->List.next = &p->Node;
        head->prev = &p->Node;
        p->Node.next = head;
        p->Object = c;
        p->Node.prev = &h->List;
    }
}

void munition_effects_do_timestep(float dt)
{
    if (TheMunitionEffectsHandler != NULL)
        munitioneffectshandler_do_timestep(TheMunitionEffectsHandler, dt);
}

// ------------------------------------------------------------ the tables

static void munition_vt_destroy(void *self, int32_t flags)
{
    munition_destroy((Munition *)self, flags);
}

static void droppedbomb_vt_destroy(void *self, int32_t flags)
{
    droppedbomb_destroy((Munition *)self, flags);
}

static void smokebomb_vt_destroy(void *self, int32_t flags)
{
    smokebomb_destroy((SmokeBomb *)self, flags);
}

static void droppedspikes_vt_destroy(void *self, int32_t flags)
{
    droppedspikes_destroy((DroppedSpikes *)self, flags);
}

static void rocket_vt_destroy(void *self, int32_t flags)
{
    rocket_destroy((Rocket *)self, flags);
}

#define E(f) { 0, 0, (VtFn)(f) }
#define PURE { 0, 0, NULL }

// Smokeable's table with Munition::Backup at 72 and the class's own
// destructor, DoSnapshot, Move, ConsiderImpulse, ApplyImpulse, GetSmokeType
// and OnLifetimeEnd. DoSnapshot is Smokeable's (smokesnap.c) but for
// DroppedSpikes' and Rocket's own, which are not ported yet (NULL).
#define MUNITION_VT(dtor, snap, move, consider, apply, smoke, life) {       \
    PURE,                                                                   \
    E(dtor),                                                                \
    E(snap),                                                                \
    E(smokeable_get_position),                                              \
    E(smokeable_get_velocity),                                              \
    E(smokeable_get_rotation),                                              \
    E(dynamiccollisionbody_set_position),                                   \
    E(dynamiccollisionbody_get_max_backup_time),                            \
    E(move),                                                                \
    E(munition_backup),                                                     \
    E(dynamiccollisionbody_interpolate),                                    \
    E(dynamiccollisionbody_recompute_auxilliaries),                         \
    E(dynamiccollisionbody_get_current_velocities),                         \
    E(dynamiccollisionbody_get_test_impulse_velocities),                    \
    E(dynamiccollisionbody_set_to_physics_mode),                            \
    E(consider),                                                            \
    E(apply),                                                               \
    E(smokeable_are_collisions_enabled),                                    \
    E(smokeable_get_terrain_type),                                          \
    E(smokeable_get_mass_inverse),                                          \
    E(smokeable_get_inertia_tensor_inverse),                                \
    E(smokeable_is_moveable),                                               \
    E(dynamiccollisionbody_change_in_energy),                               \
    E(smokeable_is_blinking),                                               \
    E(smokeable_get_bounciness),                                            \
    E(smokeable_get_friction),                                              \
    E(smoke),                                                               \
    E(life),                                                                \
}

// _vt$8Munition (0x002b7120).
static const VtEntry munition_vt[SMOKEABLE_VT_ENTRIES] =
    MUNITION_VT(munition_vt_destroy, smokeable_do_snapshot, smokeable_move,
                smokeable_consider_impulse, smokeable_apply_impulse,
                smokeable_get_smoke_type, smokeable_on_lifetime_end);

// _vt$11DroppedBomb (0x002b7020).
static const VtEntry droppedbomb_vt[SMOKEABLE_VT_ENTRIES] =
    MUNITION_VT(droppedbomb_vt_destroy, smokeable_do_snapshot,
                droppedbomb_move,
                smokeable_consider_impulse, smokeable_apply_impulse,
                smokeable_get_smoke_type, smokeable_on_lifetime_end);

// _vt$9SmokeBomb (0x002b6f20).
static const VtEntry smokebomb_vt[SMOKEABLE_VT_ENTRIES] =
    MUNITION_VT(smokebomb_vt_destroy, smokeable_do_snapshot, smokebomb_move,
                smokeable_consider_impulse, smokeable_apply_impulse,
                smokebomb_get_smoke_type, smokebomb_on_lifetime_end);

// _vt$13DroppedSpikes (0x002b6e20).
static const VtEntry droppedspikes_vt[SMOKEABLE_VT_ENTRIES] =
    MUNITION_VT(droppedspikes_vt_destroy, NULL, droppedspikes_move,
                droppedspikes_consider_impulse, droppedspikes_apply_impulse,
                droppedspikes_get_smoke_type, droppedspikes_on_lifetime_end);

// _vt$6Rocket (0x002b6d20).
static const VtEntry rocket_vt[SMOKEABLE_VT_ENTRIES] =
    MUNITION_VT(rocket_vt_destroy, NULL, rocket_move, rocket_consider_impulse,
                rocket_apply_impulse, rocket_get_smoke_type,
                rocket_on_lifetime_end);

// The PhysicsSystem tables (each 0x20 below its main one): Smokeable's,
// with the class's destructor.
static VtEntry munition_system_vt[5][SMOKEABLE_SYSTEM_VT_ENTRIES];

static void install(int k, uint32_t main_image, const VtEntry *main_vt,
                    uint32_t system_image, VtFn dtor)
{
    int16_t  d = (int16_t)-(int)offsetof(Smokeable, System);
    VtEntry *t = munition_system_vt[k];

    t[0].delta = d;
    t[0].index = 0;
    t[0].fn = NULL;
    t[1].delta = d;
    t[1].index = 0;
    t[1].fn = dtor;
    t[2].delta = d;
    t[2].index = 0;
    t[2].fn = (VtFn)smokeable_system_compute_auxiliaries;
    t[3].delta = 0;
    t[3].index = 0;
    t[3].fn = (VtFn)physicssystem_resolve_forces;
    vt_install(main_image, main_vt, SMOKEABLE_VT_ENTRIES);
    vt_install(system_image, t, SMOKEABLE_SYSTEM_VT_ENTRIES);
}

void munition_install_vtables(void)
{
    install(0, MUNITION_VTABLE, munition_vt, MUNITION_SYSTEM_VTABLE,
            (VtFn)munition_vt_destroy);
    install(1, DROPPEDBOMB_VTABLE, droppedbomb_vt, DROPPEDBOMB_SYSTEM_VTABLE,
            (VtFn)droppedbomb_vt_destroy);
    install(2, SMOKEBOMB_VTABLE, smokebomb_vt, SMOKEBOMB_SYSTEM_VTABLE,
            (VtFn)smokebomb_vt_destroy);
    install(3, DROPPEDSPIKES_VTABLE, droppedspikes_vt,
            DROPPEDSPIKES_SYSTEM_VTABLE, (VtFn)droppedspikes_vt_destroy);
    install(4, ROCKET_VTABLE, rocket_vt, ROCKET_SYSTEM_VTABLE,
            (VtFn)rocket_vt_destroy);
}
