// collision -- see collision.h.
//
// Collision.obj whole: InitCollision and CloseCollision, the
// constructor and destructor, AddImpulse, Update, End, GetTerrainType and
// the four questions about who is in it, and the inline bTNode destructor
// and operator delete beside them. The sixteenth slice of task 27.
//
// AddImpulse's vectors are the VU's quadwords, as contact.c's are: the add
// is all four lanes, and a length is `sqrt.s` of the squares summed x, then
// y, then z.
//
// Retail's: the 112-byte record and ImpulseDirection (step 8m-4b).

#include "collision.h"

#include <math.h>
#include <stddef.h>

#include "car.h"
#include "eefpu.h"
#include "realtime.h"
#include "replay.h"
#include "terraintype.h"
#include "vtable.h"
#include "world.h"

// ------------------------------------------------------------ the globals

BSlotPool *CollisionSlotPool;
float      CollisionLifetime = 0.3f;        // 0x00331ae4  3e99999a

struct CollisionSample *(*gCollisionSoundCreateSampleFn)(Collision *c);
void (*gCollisionSoundReleaseSampleFn)(Collision *c);
void (*gCollisionSoundPlayScrapeFn)(Collision *c);

void *pTerrainEffectEmitters;
void (*gTerrainEffectTriggerFn)(void *emitters, int32_t effect,
                                int32_t terrain, float scale,
                                const bVector3 *at, const bVector3 *velocity);

// The literals. The two distances are built with `lui`; the tick is
// gp-27200, 0.00025 (3983126f), a second over 4000.
#define SAMPLE_DISTANCE   100.0f            // 42c80000
#define EFFECT_DISTANCE    50.0f            // 42480000
#define TICK_SECONDS      0.00025f

// The list head is World's, a node standing alone; a node is the first
// thing in a Collision, so the head passes for one wherever only the links
// are touched.
static Collision *cnode(WorldList *l)
{
    return (Collision *)(void *)l;
}

// ------------------------------------------------------------- the lanes

// `vmul.xyz ; vaddy.x ; vaddz.x`.
static float dot3(const bVector3 *a, const bVector3 *b)
{
    return (a->x * b->x + a->y * b->y) + a->z * b->z;
}

// `vrsqrt Q,vf00w,vf02x ; vaddq.x ; vmulx.xyzw`: all four lanes over the
// length of three. The VU divides a zero length the EE's way, FLT_MAX.
static void normalize4(bVector3 *out, const bVector3 *v)
{
    float inv = 0.0f + ee_div(1.0f, sqrtf(dot3(v, v)));

    out->x = v->x * inv;
    out->y = v->y * inv;
    out->z = v->z * inv;
    out->pad = v->pad * inv;
}

// `min.s` and `max.s`, fs then ft.
static float min_s(float fs, float ft)
{
    return ft < fs ? ft : fs;
}

static float max_s(float fs, float ft)
{
    return fs < ft ? ft : fs;
}

// ------------------------------------------------------------- the table

typedef bVector3 *(*VtVectorFn)(void *self);
typedef int32_t (*VtTerrainFn)(void *self);

static bVector3 *get_velocity(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_VELOCITY);

    return ((VtVectorFn)e->fn)(vt_this(b, e));
}

static int32_t get_terrain_type(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_TERRAIN_TYPE);

    return ((VtTerrainFn)e->fn)(vt_this(b, e));
}

// ------------------------------------------------------------- the seams

static struct CollisionSample *create_sample(Collision *c)
{
    if (gCollisionSoundCreateSampleFn == NULL)
        return NULL;
    return gCollisionSoundCreateSampleFn(c);
}

static void release_sample(Collision *c)
{
    if (gCollisionSoundReleaseSampleFn != NULL)
        gCollisionSoundReleaseSampleFn(c);
}

static void play_scrape(Collision *c)
{
    if (gCollisionSoundPlayScrapeFn != NULL)
        gCollisionSoundPlayScrapeFn(c);
}

static void trigger_effect(int32_t effect, int32_t terrain, float scale,
                           const bVector3 *at, const bVector3 *velocity)
{
    if (gTerrainEffectTriggerFn != NULL)
        gTerrainEffectTriggerFn(pTerrainEffectEmitters, effect, terrain,
                                scale, at, velocity);
}

// ------------------------------------------------------------ the object

void init_collision(void)
{
    CollisionSlotPool = bNewSlotPool((int)sizeof(Collision), 32,
                                     "CollisionSlotPool", 16);
}

void close_collision(void)
{
    bDeleteSlotPool(CollisionSlotPool);
    CollisionSlotPool = NULL;
}

Collision *collision_construct(Collision *c, CollisionBodyWitness *w,
                               bVector3 *pt)
{
    WorldList *list = &pCurrentWorld->CollisionList;
    Collision *last = list->prev;

    // bTList::AddTail. TotalImpulse's fourth lane is not written.
    c->TotalImpulse.x = 0.0f;
    last->Link.next = c;
    list->prev = c;
    c->TotalImpulse.z = 0.0f;
    c->TotalImpulse.y = 0.0f;
    c->pWitness = w;
    c->Link.prev = last;
    c->Link.next = cnode(list);
    c->CollisionTime.PackedTime = 0;
    c->LastContactTime.PackedTime = 0;
    c->TotalImpulseMagnitude = 0.0f;
    c->Scrape = NULL;
    if (pt == NULL) {
        c->InitialContactPoint.x = 0.0f;
        c->InitialContactPoint.z = 0.0f;
        c->InitialContactPoint.y = 0.0f;
    } else {
        c->InitialContactPoint = *pt;
        if (world_get_distance_to_closest_player(pCurrentWorld, pt)
            < SAMPLE_DISTANCE)
            c->Sample = create_sample(c);
    }
    c->LastContactTime.PackedTime = (uint32_t)WorldTimer;
    c->CollisionTime.PackedTime = (uint32_t)WorldTimer;
    // Retail's. The fourth lane is not written.
    c->ImpulseDirection.x = 0.0f;
    c->ImpulseDirection.z = 0.0f;
    c->ImpulseDirection.y = 0.0f;
    return c;
}

Collision *collision_new(CollisionBodyWitness *w, bVector3 *pt)
{
    return collision_construct(bSlotOMalloc(CollisionSlotPool), w, pt);
}

void collision_delete(void *p)
{
    bSlotFree(CollisionSlotPool, p);
}

void collision_destroy(Collision *c, int32_t flags)
{
    Collision *next = c->Link.next;
    Collision *prev = c->Link.prev;

    // The unlink's second store is in the call's delay slot.
    prev->Link.next = next;
    next->Link.prev = prev;
    release_sample(c);
    // ~bTNode with flags 0 does nothing.
    if (flags & 1)
        collision_delete(c);
}

void collision_add_impulse(Collision *c, bVector3 *at, bVector3 *impulse,
                           float scrape)
{
    bVector2 ground;
    float len;

    c->TotalImpulse.x = c->TotalImpulse.x + impulse->x;
    c->TotalImpulse.y = c->TotalImpulse.y + impulse->y;
    c->TotalImpulse.z = c->TotalImpulse.z + impulse->z;
    c->TotalImpulse.pad = c->TotalImpulse.pad + impulse->pad;
    len = sqrtf(dot3(impulse, impulse));
    c->TotalImpulseMagnitude = c->TotalImpulseMagnitude + len;
    c->LastContactTime.PackedTime = (uint32_t)WorldTimer;
    c->CurrentContactPoint = *at;
    c->CurrentScrapeSpeed = scrape;

    // The bVector2 overload, on the point's first two lanes.
    ground.x = at->x;
    ground.y = at->y;
    if (world_get_distance_to_closest_player_2d(pCurrentWorld, &ground)
        < EFFECT_DISTANCE) {
        int32_t tt = collision_get_terrain_type(c);
        const TerrainTypeInfo *info = &TerrainTypeInfoTable[tt];

        if (info->CollisionScrapeMinSpeed < scrape) {
            float lo = info->CollisionScrapeMinSpeed;
            float s;
            bVector3 *v1, *v2, *v;
            float l1, l2;

            // ROAD's and POTHOLE's range is 50 to 50: the EE's divide.
            s = ee_div(scrape - lo, info->CollisionScrapeMaxSpeed - lo);
            s = min_s(1.0f, max_s(s, 0.0f));

            // The faster of the two velocities -- but both calls are on
            // the first body, and both lengths are of the first answer, so
            // it is always the first.
            v1 = get_velocity(c->pWitness->pBody1);
            v2 = get_velocity(c->pWitness->pBody1);
            l1 = sqrtf(dot3(v1, v1));
            l2 = sqrtf(dot3(v1, v1));
            v = v1;
            if (l2 < l1)
                v = v2;
            trigger_effect(TERRAIN_EFFECT_COLLISION_SCRAPE, tt, s, at, v);
            play_scrape(c);
        }
        if (info->CollisionImpactMinForce < len) {
            float lo = info->CollisionImpactMinForce;
            float s;
            bVector3 zero;

            s = (len - lo) / (info->CollisionImpactMaxForce - lo);
            s = min_s(1.0f, max_s(s, 0.0f));
            // Three words of the stack. The image leaves the fourth as the
            // stack had it; here it is zero, as vclip.c's are.
            zero.x = 0.0f;
            zero.y = 0.0f;
            zero.z = 0.0f;
            zero.pad = 0.0f;
            trigger_effect(TERRAIN_EFFECT_COLLISION_IMPACT, tt, s, at, &zero);
        }
        // Retail's: read again from the impulse after the effects.
        normalize4(&c->ImpulseDirection, impulse);
    }
}

int32_t collision_update(Collision *c, float dt)
{
    int32_t age = (int32_t)((uint32_t)WorldTimer
                            - c->LastContactTime.PackedTime);

    (void)dt;
    return (float)age * TICK_SECONDS < CollisionLifetime;
}

void collision_end(Collision *c)
{
    cbwitness_end_collision(c->pWitness);
}

int32_t collision_get_terrain_type(Collision *c)
{
    int32_t t1 = get_terrain_type(c->pWitness->pBody1);
    int32_t t2 = get_terrain_type(c->pWitness->pBody2);

    if (TerrainTypeInfoTable[t2].CollisionPriority
        <= TerrainTypeInfoTable[t1].CollisionPriority)
        return t1;
    return t2;
}

int32_t collision_is_two_car_collision(Collision *c)
{
    CollisionBodyWitness *w = c->pWitness;

    if (w->pBody1->Type != CAR_COLLISION_BODY)
        return 0;
    return w->pBody2->Type == CAR_COLLISION_BODY;
}

void collision_get_colliding_cars(Collision *c, struct Car **car1,
                                  struct Car **car2)
{
    CollisionBodyWitness *w = c->pWitness;

    *car1 = NULL;
    *car2 = NULL;
    if (w->pBody1->Type == CAR_COLLISION_BODY)
        *car1 = ((CarCollisionBody *)(void *)w->pBody1)->pCar;
    if (w->pBody2->Type == CAR_COLLISION_BODY)
        *car2 = ((CarCollisionBody *)(void *)w->pBody2)->pCar;
}

int32_t collision_is_player_involved(Collision *c)
{
    struct Car *car1, *car2;

    collision_get_colliding_cars(c, &car1, &car2);
    if (car1 != NULL && car1->pPlayer != NULL)
        return 1;
    if (car2 == NULL)
        return 0;
    return car2->pPlayer != NULL;
}

int32_t collision_is_smokeable_involved(Collision *c)
{
    CollisionBodyWitness *w = c->pWitness;

    if (w->pBody1->Type == SMOKEABLE_COLLISION_BODY)
        return 1;
    return w->pBody2->Type == SMOKEABLE_COLLISION_BODY;
}

// ---------------------------------------------------------------- the replay

// 0x0021e760. The scrape speed and the impulse's direction are not in it.
void collision_do_snapshot(Collision *c, ReplaySnapshot *s)
{
    ReplaySnapshot_BeginSection(s, c, "Collision");
    ReplaySnapshot_MoveTimer(s, (int32_t *)&c->CollisionTime.PackedTime);
    ReplaySnapshot_MoveTimer(s, (int32_t *)&c->LastContactTime.PackedTime);
    ReplaySnapshot_MoveVector3(s, &c->InitialContactPoint);
    ReplaySnapshot_MoveVector3(s, &c->CurrentContactPoint);
    ReplaySnapshot_MoveVector3(s, &c->TotalImpulse);
    ReplaySnapshot_MoveFloat(s, &c->TotalImpulseMagnitude);
    ReplaySnapshot_EndSection(s);
}
