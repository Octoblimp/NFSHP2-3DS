// collision -- Collision.obj (0x0020b238 .. 0x0020b87c): the record of two
// bodies in contact, which lives from the first touch until they have been
// apart for CollisionLifetime.
//
// A witness makes one when its bodies first touch (BeginCollision,
// contact.c) and hands it every impulse CollisionImpulse applies
// (AddImpulse). It is on World's CollisionList from birth, so the sound and
// the damage can walk every collision in the world, and World's
// DoTimestepCollisions ends it once Update says no contact has come for a
// while. What it keeps is what those readers ask: when it began and when it
// was last touched, where, how hard in all, and how fast the surfaces slid.
// The start of a nearby one and every scrape and hard knock near a player
// reach the sound and the terrain's particles.
//
// The sixteenth slice of task 27. The image's DoSnapshot (0x0020b3c0) is the
// replay's, which the port does not have.
//
// docs/formats/collision.md has the decode.

#ifndef COLLISION_H
#define COLLISION_H

#include <stddef.h>
#include <stdint.h>

#include "bslotpool.h"
#include "bvector.h"
#include "collisionbody.h"
#include "timer.h"

struct Car;
struct CollisionSample;

typedef struct CollisionNode {
    struct Collision *next;                     // 0
    struct Collision *prev;                     // 4
} CollisionNode;                                // 8

//   Collision:Tt254=s96!1,020,245               base bTNode<Collision>
//
// No virtuals. InitialContactPoint's fourth lane is the point's own, or left
// as the pool gave it when there is no point; CurrentContactPoint and
// CurrentScrapeSpeed are only written by AddImpulse, and Sample only when the
// constructor asks the sound for one.
typedef struct Collision {
    CollisionNode Link;                         //  0  bTNode<Collision>
    Timer     CollisionTime;                    //  8
    Timer     LastContactTime;                  // 12
    bVector3  InitialContactPoint;              // 16
    bVector3  CurrentContactPoint;              // 32
    float     CurrentScrapeSpeed;               // 48
    uint8_t   _pad52[12];                       // 52  the quadword round-up
    bVector3  TotalImpulse;                     // 64
    float     TotalImpulseMagnitude;            // 80
    CollisionBodyWitness *pWitness;             // 84
    struct CollisionSample *Sample;             // 88
    struct CollisionSample *Scrape;             // 92
} Collision;                                    // 96

// Offset n on the console plus k pointers' worth of slack on a wider host.
typedef char collision_layout_check[
    (CB_AT(Collision, CollisionTime, 8, 2)
     && CB_AT(Collision, InitialContactPoint, 16, 2)
     && CB_AT(Collision, CurrentScrapeSpeed, 48, 2)
     && CB_AT(Collision, TotalImpulse, 64, 2)
     && CB_AT(Collision, TotalImpulseMagnitude, 80, 2)
     && CB_AT(Collision, pWitness, 84, 3)
     && CB_AT(Collision, Sample, 88, 4)
     && CB_AT(Collision, Scrape, 92, 5)
     && sizeof(Collision) == CB_ROUND(96 + 5 * CB_SLACK)) ? 1 : -1];

// ------------------------------------------------------------ the globals

// gp-16760, 0x00324a78. Made by InitCollision.
extern BSlotPool *CollisionSlotPool;

// gp-16764, 0x00324a74, 0.3 (3e99999a): how long, in seconds, a collision
// outlives its last contact. Nothing writes it.
extern float CollisionLifetime;

// ---------------------------------------------------------------- the seams
//
// What a collision starts outside the collision system, none of it ported:
// collision_sound's sample for a new collision (0x001d7c20), its release
// (0x001d7d60) and its scrape (0x001d80e0), which are task 29's; and
// TerrainEffectEmitters::TriggerEffect (0x0020e350) on pTerrainEffectEmitters
// (gp-16704, 0x00324ab0), the particles. The image calls all four with no
// test. A NULL seam skips the call -- a collision makes no sound and no
// sparks -- and CreateSample's skipped answer is NULL, which is also what the
// sound hands back when it has no voice to give.
extern struct CollisionSample *(*gCollisionSoundCreateSampleFn)(Collision *c);
extern void (*gCollisionSoundReleaseSampleFn)(Collision *c);
extern void (*gCollisionSoundPlayScrapeFn)(Collision *c);

// TerrainEffect's two a collision triggers.
#define TERRAIN_EFFECT_COLLISION_IMPACT 5
#define TERRAIN_EFFECT_COLLISION_SCRAPE 6

extern void *pTerrainEffectEmitters;
extern void (*gTerrainEffectTriggerFn)(void *emitters, int32_t effect,
                                       int32_t terrain, float scale,
                                       const bVector3 *at,
                                       const bVector3 *velocity);

// ---------------------------------------------------------------- the calls

// 0x0020b238 and 0x0020b268. bNewSlotPool(96, 32, "CollisionSlotPool", 16),
// and its delete. EndGameFlowLoadingTrackSpecific and
// BeginGameFlowUnloadingTrackSpecific are the callers.
void init_collision(void);
void close_collision(void);

// 0x0020b290. Onto the tail of pCurrentWorld's CollisionList, stamped now,
// with nothing added up yet. With a point: the point kept, and a sample
// asked for if a player is within 100. Without one: the point's first
// three lanes zeroed.
Collision *collision_construct(Collision *c, CollisionBodyWitness *w,
                               bVector3 *pt);

// `new Collision(w, pt)`, as BeginCollision (0x001cbe18) writes it:
// bOMalloc on CollisionSlotPool and the constructor on what it gives, with
// no test. The pool keeps the default flags, so a full one grows and every
// slot comes out zeroed: a field the constructor does not write is 0.
// contact.c's gCollisionNewFn.
Collision *collision_new(CollisionBodyWitness *w, bVector3 *pt);

// 0x0020b358. Off the list, the sample released, and the slot back to the
// pool when flags & 1. collisionbody.c's gCollisionDestroyFn, with 3.
void collision_destroy(Collision *c, int32_t flags);

// 0x0020b870. bFree on CollisionSlotPool.
void collision_delete(void *p);

// 0x0020b450. One impulse of a contact at `at`: added in (all four lanes)
// with its length, the contact stamped and kept, and `scrape` as the
// sliding speed. Within 50 of a player on the ground plane, a scrape past
// the terrain's minimum makes its sparks and sound, and a knock past its
// minimum force its impact. contact.c's gCollisionAddImpulseFn.
void collision_add_impulse(Collision *c, bVector3 *at, bVector3 *impulse,
                           float scrape);

// 0x0020b668. Whether the last contact is younger than CollisionLifetime.
// The argument is the timestep, and is not read.
int32_t collision_update(Collision *c, float dt);

// 0x0020b6a8. The witness's EndCollision, which destroys this.
void collision_end(Collision *c);

// 0x0020b6b0. The two bodies' terrains, and whichever has the higher
// CollisionPriority; the first on a tie.
int32_t collision_get_terrain_type(Collision *c);

// 0x0020b748. Both bodies cars.
int32_t collision_is_two_car_collision(Collision *c);

// 0x0020b770. Each body's Car if it is a car's body, else NULL.
void collision_get_colliding_cars(Collision *c, struct Car **car1,
                                  struct Car **car2);

// 0x0020b7b8. Either car has a Player.
int32_t collision_is_player_involved(Collision *c);

// 0x0020b800. Either body a smokeable's.
int32_t collision_is_smokeable_involved(Collision *c);

// The inline getters the stab lists that only hand back a field. Its
// IsStillActive, GetAge and GetTimeSinceLastContact are inline too, and no
// caller ported yet has expanded one, so they wait for the first that does.
static inline Timer collision_get_collision_time(const Collision *c)
{
    return c->CollisionTime;
}

static inline bVector3 *collision_get_initial_contact_point(Collision *c)
{
    return &c->InitialContactPoint;
}

static inline bVector3 *collision_get_current_contact_point(Collision *c)
{
    return &c->CurrentContactPoint;
}

static inline bVector3 *collision_get_total_impulse(Collision *c)
{
    return &c->TotalImpulse;
}

static inline float collision_get_total_impulse_magnitude(const Collision *c)
{
    return c->TotalImpulseMagnitude;
}

static inline float collision_get_scrape_speed(const Collision *c)
{
    return c->CurrentScrapeSpeed;
}

static inline struct CollisionSample *collision_get_sound(const Collision *c)
{
    return c->Sample;
}

static inline struct CollisionSample *collision_get_scrape(const Collision *c)
{
    return c->Scrape;
}

static inline void collision_set_sound(Collision *c,
                                       struct CollisionSample *s)
{
    c->Sample = s;
}

static inline void collision_set_scrape(Collision *c,
                                        struct CollisionSample *s)
{
    c->Scrape = s;
}

#endif
