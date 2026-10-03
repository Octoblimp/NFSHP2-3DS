// collision_test -- the harness tools/collision_check.py runs against
// retail's Collision.obj, 3DS Files/source/collision.c, and World's two
// GetDistanceToClosestPlayer overloads in world.c.
//
// It reads a script of hex words from argv[1], one op and its operands at a
// time (the checker has the list), and prints what the model prints for the
// image. The script names a collision by the order it was made in; the
// labels, which are the checker's, say where things are: Cn is slot n of
// CollisionSlotPool, R0 and R1 the two collisions built outside it on
// memory filled with 0xa5 (dirty is a pointer read out of that fill), head
// the World's CollisionList, W0..W3 the stand-in
// witnesses, B0..B3 the stand-in bodies (car-body sized, on one recording
// vtable whose two slots take `this` eight bytes in), Bn.v what body n's
// GetVelocity answers, CAR0 and CAR1 real Cars, S1..S4 what the sound's
// CreateSample hands out, TEE the emitters, at and imp the impulse's two
// vectors, P0..P3 the constructor's points, and local anything else, which
// is the port's stack. The four seams and the witness's EndCollision are
// this file's, and log.
//
//     collision_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bslotpool.h"
#include "car.h"
#include "collision.h"
#include "collisionbody.h"
#include "realtime.h"
#include "vtable.h"
#include "world.h"

enum {
    OP_TAG = 1, OP_INIT, OP_CLOSE, OP_NEW, OP_DESTROY, OP_IMPULSE,
    OP_UPDATE, OP_END, OP_TT, OP_TWO, OP_CARS, OP_PLAYER, OP_SMOKE,
    OP_BODY, OP_WITNESS, OP_BODYCAR, OP_CARPLAYER, OP_PLAYERS, OP_TIMER,
    OP_LIFETIME, OP_SAMPLE, OP_DUMP, OP_LIST, OP_POINT, OP_DIST3, OP_DIST2,
    OP_RAW,
};

#define NB   4
#define NW   4
#define NCAR 2
#define NS   4
#define NPT  4
#define NSLOT 32

// The fake vtable's image address, and the delta its two slots add.
#define FAKE_VT 0x01F00000u
#define DELTA   8

// WorldTimer is realtime.c's; the harness does not link the clock.
int32_t WorldTimer;

static FILE *script;

static World world;
static CarCollisionBody *bodies[NB];
static _Alignas(16) bVector3 vel[NB];
static int32_t terrain[NB];
static CollisionBodyWitness witnesses[NW];
static struct Car *cars[NCAR];
static int fake_player;
static int samples[NS];
static int tee;
static _Alignas(16) bVector3 pts[NPT];
static _Alignas(16) bVector3 at_v;
static _Alignas(16) bVector3 imp_v;

// Two collisions outside the pool, filled with 0xa5 before the constructor
// runs on them: the pool zeroes a slot, and would hide every field the
// constructor zeroes itself.
static _Alignas(16) Collision raw[2];
#define DIRTY ((uintptr_t)0xa5a5a5a5a5a5a5a5ull)

static int sample_queue[4096];
static int sq_head, sq_tail;

static _Alignas(16) uint8_t arena[BSLOTPOOL_HEADER_SIZE
                                  + NSLOT * sizeof(Collision) + 64];

static uint32_t next(void)
{
    unsigned int w;

    if (fscanf(script, "%x", &w) != 1) {
        fprintf(stderr, "script ends inside an op\n");
        exit(2);
    }
    return (uint32_t)w;
}

static float as_float(uint32_t b)
{
    float f;

    memcpy(&f, &b, 4);
    return f;
}

static uint32_t fb(float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    return b;
}

static void read_vec(bVector3 *v)
{
    v->x = as_float(next());
    v->y = as_float(next());
    v->z = as_float(next());
    v->pad = as_float(next());
}

// ------------------------------------------------------------ the labels

static const char *label(const void *p)
{
    static char buf[8][32];
    static int k;
    char *b = buf[k++ & 7];
    int i;

    if (p == NULL)
        return "null";
    if ((uintptr_t)p == DIRTY)
        return "dirty";
    for (i = 0; i < 2; i++)
        if (p == (const void *)&raw[i]) {
            snprintf(b, 32, "R%d", i);
            return b;
        }
    if (p == (const void *)&world.CollisionList)
        return "head";
    if (CollisionSlotPool != NULL) {
        const char *base = (const char *)CollisionSlotPool
                           + BSLOTPOOL_HEADER_SIZE;
        ptrdiff_t d = (const char *)p - base;

        if (d >= 0 && d < (ptrdiff_t)CollisionSlotPool->numSlots
                              * CollisionSlotPool->slotSize) {
            if (d % CollisionSlotPool->slotSize != 0)
                snprintf(b, 32, "C%d+%d",
                         (int)(d / CollisionSlotPool->slotSize),
                         (int)(d % CollisionSlotPool->slotSize));
            else
                snprintf(b, 32, "C%d",
                         (int)(d / CollisionSlotPool->slotSize));
            return b;
        }
    }
    for (i = 0; i < NW; i++)
        if (p == (const void *)&witnesses[i]) {
            snprintf(b, 32, "W%d", i);
            return b;
        }
    for (i = 0; i < NB; i++) {
        if (p == (const void *)bodies[i]) {
            snprintf(b, 32, "B%d", i);
            return b;
        }
        if (p == (const void *)&vel[i]) {
            snprintf(b, 32, "B%d.v", i);
            return b;
        }
    }
    for (i = 0; i < NCAR; i++)
        if (p == (const void *)cars[i]) {
            snprintf(b, 32, "CAR%d", i);
            return b;
        }
    for (i = 0; i < NS; i++)
        if (p == (const void *)&samples[i]) {
            snprintf(b, 32, "S%d", i + 1);
            return b;
        }
    if (p == (const void *)&tee)
        return "TEE";
    if (p == (const void *)&at_v)
        return "at";
    if (p == (const void *)&imp_v)
        return "imp";
    for (i = 0; i < NPT; i++)
        if (p == (const void *)&pts[i]) {
            snprintf(b, 32, "P%d", i);
            return b;
        }
    return "local";
}

// ------------------------------------------------------------ the pool

static void *arena_alloc(size_t bytes, const char *name, int memoryPool)
{
    if (strcmp(name, "CollisionSlotPool") != 0) {
        fprintf(stderr, "no arena for pool %s\n", name);
        exit(3);
    }
    if (bytes > sizeof arena) {
        fprintf(stderr, "pool %s of %zu bytes does not fit\n", name, bytes);
        exit(3);
    }
    printf("  pool alloc %s mp %d\n", name, memoryPool);
    memset(arena, 0, sizeof arena);
    return arena;
}

static void arena_release(void *block)
{
    printf("  pool free %s\n", block == (void *)arena ? "CollisionSlotPool"
                                                      : "?");
}

static void printf_hook(const char *text)
{
    (void)text;
    printf("  printf\n");
}

// ------------------------------------------------------------ the bodies

static int body_of(void *self)
{
    int i;

    for (i = 0; i < NB; i++)
        if ((char *)self - DELTA == (char *)bodies[i])
            return i;
    fprintf(stderr, "a slot called on a stranger\n");
    exit(3);
}

static bVector3 *fake_get_velocity(void *self)
{
    int k = body_of(self);

    printf("  vel B%d\n", k);
    return &vel[k];
}

static int32_t fake_get_terrain_type(void *self)
{
    int k = body_of(self);

    printf("  tt B%d -> %d\n", k, terrain[k]);
    return terrain[k];
}

static void install_vtable(void)
{
    static VtEntry entries[COLLISIONBODY_VT_ENTRIES];

    entries[VT_SLOT(COLLISIONBODY_VT_GET_VELOCITY)].delta = DELTA;
    entries[VT_SLOT(COLLISIONBODY_VT_GET_VELOCITY)].fn =
        (VtFn)fake_get_velocity;
    entries[VT_SLOT(COLLISIONBODY_VT_GET_TERRAIN_TYPE)].delta = DELTA;
    entries[VT_SLOT(COLLISIONBODY_VT_GET_TERRAIN_TYPE)].fn =
        (VtFn)fake_get_terrain_type;
    vt_install(FAKE_VT, entries, COLLISIONBODY_VT_ENTRIES);
}

// ------------------------------------------------------------ the seams

static struct CollisionSample *seam_create(Collision *c)
{
    int s = sq_head < sq_tail ? sample_queue[sq_head++] : 0;
    void *p = s ? (void *)&samples[s - 1] : NULL;

    printf("  create sample %s -> %s\n", label(c), label(p));
    return (struct CollisionSample *)p;
}

static void seam_release(Collision *c)
{
    printf("  release sample %s (%s)\n", label(c), label(c->Sample));
}

static void seam_scrape(Collision *c)
{
    printf("  play scrape %s\n", label(c));
}

static void seam_trigger(void *emitters, int32_t effect, int32_t terrain_,
                         float scale, const bVector3 *at,
                         const bVector3 *velocity)
{
    printf("  effect %s %d tt %d scale %08x at %s %08x %08x %08x"
           " vel %s %08x %08x %08x\n",
           label(emitters), effect, terrain_, (unsigned)fb(scale),
           label(at), (unsigned)fb(at->x), (unsigned)fb(at->y),
           (unsigned)fb(at->z), label(velocity), (unsigned)fb(velocity->x),
           (unsigned)fb(velocity->y), (unsigned)fb(velocity->z));
}

void cbwitness_end_collision(CollisionBodyWitness *w)
{
    printf("  end collision %s\n", label(w));
}

// ------------------------------------------------------------ the ops

// The script names a collision by the order it was made in.
static Collision *handles[4096];
static int nhandles;

static Collision *slot(uint32_t i)
{
    if ((int)i >= nhandles) {
        fprintf(stderr, "no handle %u\n", (unsigned)i);
        exit(3);
    }
    return handles[i];
}

static void v4(const char *name, const bVector3 *v)
{
    printf(" %s %08x %08x %08x %08x", name, (unsigned)fb(v->x),
           (unsigned)fb(v->y), (unsigned)fb(v->z), (unsigned)fb(v->pad));
}

static void dump(Collision *c)
{
    printf("  %s next %s prev %s ct %08x lct %08x\n", label(c),
           label(c->Link.next), label(c->Link.prev),
           (unsigned)c->CollisionTime.PackedTime,
           (unsigned)c->LastContactTime.PackedTime);
    printf(" ");
    v4("init", &c->InitialContactPoint);
    v4("cur", &c->CurrentContactPoint);
    printf(" speed %08x\n", (unsigned)fb(c->CurrentScrapeSpeed));
    printf(" ");
    v4("imp", &c->TotalImpulse);
    printf(" mag %08x wit %s sample %s scrape %s\n",
           (unsigned)fb(c->TotalImpulseMagnitude), label(c->pWitness),
           label(c->Sample), label(c->Scrape));
    printf(" ");
    v4("dir", &c->ImpulseDirection);
    printf("\n");
}

static void list(void)
{
    const Collision *head = (const Collision *)(void *)&world.CollisionList;
    const Collision *p;
    int n;

    printf("  fwd");
    for (p = world.CollisionList.next, n = 0; p != head && n < 40;
         p = p->Link.next, n++)
        printf(" %s", label(p));
    printf("\n  back");
    for (p = world.CollisionList.prev, n = 0; p != head && n < 40;
         p = p->Link.prev, n++)
        printf(" %s", label(p));
    printf("\n");
}

static void step(uint32_t op)
{
    switch (op) {
    case OP_TAG:
        printf("[%u]\n", (unsigned)next());
        break;
    case OP_INIT:
    case OP_CLOSE:
        printf(op == OP_INIT ? "init\n" : "close\n");
        if (op == OP_INIT)
            init_collision();
        else
            close_collision();
        if (CollisionSlotPool != NULL)
            printf("  pool made, %d slots\n", CollisionSlotPool->numSlots);
        else
            printf("  pool null\n");
        break;
    case OP_NEW: {
        uint32_t w = next();
        uint32_t p = next();
        Collision *c;

        printf("new W%u P%d\n", (unsigned)w, (int)p - 1);
        c = collision_new(&witnesses[w], p != 0 ? &pts[p - 1] : NULL);
        if (nhandles == 4096) {
            fprintf(stderr, "too many handles\n");
            exit(2);
        }
        handles[nhandles++] = c;
        printf("  -> %s\n", label(c));
        dump(c);
        break;
    }
    case OP_DESTROY: {
        Collision *c = slot(next());
        int32_t flags = (int32_t)next();

        printf("destroy %s %d\n", label(c), flags);
        collision_destroy(c, flags);
        break;
    }
    case OP_IMPULSE: {
        Collision *c = slot(next());
        float scrape;

        read_vec(&at_v);
        read_vec(&imp_v);
        scrape = as_float(next());
        printf("impulse %s at %08x %08x %08x %08x imp %08x %08x %08x %08x"
               " scrape %08x\n", label(c), (unsigned)fb(at_v.x),
               (unsigned)fb(at_v.y), (unsigned)fb(at_v.z),
               (unsigned)fb(at_v.pad), (unsigned)fb(imp_v.x),
               (unsigned)fb(imp_v.y), (unsigned)fb(imp_v.z),
               (unsigned)fb(imp_v.pad), (unsigned)fb(scrape));
        collision_add_impulse(c, &at_v, &imp_v, scrape);
        dump(c);
        break;
    }
    case OP_UPDATE: {
        Collision *c = slot(next());
        uint32_t dt = next();

        printf("update %s %08x -> %d\n", label(c), (unsigned)dt,
               collision_update(c, as_float(dt)));
        break;
    }
    case OP_END: {
        Collision *c = slot(next());

        printf("end %s\n", label(c));
        collision_end(c);
        break;
    }
    case OP_TT: {
        Collision *c = slot(next());

        printf("tt %s\n", label(c));
        printf("  -> %d\n", collision_get_terrain_type(c));
        break;
    }
    case OP_TWO: {
        Collision *c = slot(next());

        printf("two %s -> %d\n", label(c), collision_is_two_car_collision(c));
        break;
    }
    case OP_CARS: {
        Collision *c = slot(next());
        struct Car *c1 = (struct Car *)(void *)&tee;
        struct Car *c2 = (struct Car *)(void *)&tee;

        collision_get_colliding_cars(c, &c1, &c2);
        printf("cars %s -> %s %s\n", label(c), label(c1), label(c2));
        break;
    }
    case OP_PLAYER: {
        Collision *c = slot(next());

        printf("player %s -> %d\n", label(c), collision_is_player_involved(c));
        break;
    }
    case OP_SMOKE: {
        Collision *c = slot(next());

        printf("smoke %s -> %d\n", label(c),
               collision_is_smokeable_involved(c));
        break;
    }
    case OP_BODY: {
        uint32_t k = next();
        uint32_t type = next();

        terrain[k] = (int32_t)next();
        read_vec(&vel[k]);
        bodies[k]->Dynamic.Body.Type = (int8_t)(uint8_t)type;
        printf("body B%u type %d tt %d\n", (unsigned)k,
               bodies[k]->Dynamic.Body.Type, terrain[k]);
        break;
    }
    case OP_WITNESS: {
        uint32_t w = next();
        uint32_t b1 = next();
        uint32_t b2 = next();

        witnesses[w].pBody1 = &bodies[b1]->Dynamic.Body;
        witnesses[w].pBody2 = &bodies[b2]->Dynamic.Body;
        printf("witness W%u B%u B%u\n", (unsigned)w, (unsigned)b1,
               (unsigned)b2);
        break;
    }
    case OP_BODYCAR: {
        uint32_t k = next();
        int32_t car = (int32_t)next();

        bodies[k]->pCar = car >= 0 ? cars[car] : NULL;
        printf("bodycar B%u %s\n", (unsigned)k, label(bodies[k]->pCar));
        break;
    }
    case OP_CARPLAYER: {
        uint32_t k = next();
        uint32_t on = next();

        cars[k]->pPlayer = on ? (Player *)(void *)&fake_player : NULL;
        printf("carplayer CAR%u %u\n", (unsigned)k, (unsigned)on);
        break;
    }
    case OP_PLAYERS:
        read_vec(&world.PlayerPositions[0]);
        read_vec(&world.PlayerPositions[1]);
        printf("players");
        v4("p0", &world.PlayerPositions[0]);
        v4("p1", &world.PlayerPositions[1]);
        printf("\n");
        break;
    case OP_TIMER:
        WorldTimer = (int32_t)next();
        printf("timer %08x\n", (unsigned)WorldTimer);
        break;
    case OP_LIFETIME:
        CollisionLifetime = as_float(next());
        printf("lifetime %08x\n", (unsigned)fb(CollisionLifetime));
        break;
    case OP_SAMPLE:
        if (sq_tail == 4096) {
            fprintf(stderr, "sample queue overflow\n");
            exit(2);
        }
        sample_queue[sq_tail++] = (int)next();
        break;
    case OP_DUMP:
        dump(slot(next()));
        break;
    case OP_LIST:
        printf("list\n");
        list();
        break;
    case OP_POINT: {
        uint32_t k = next();

        read_vec(&pts[k]);
        printf("point P%u", (unsigned)k);
        v4("", &pts[k]);
        printf("\n");
        break;
    }
    case OP_DIST3: {
        _Alignas(16) bVector3 p;

        read_vec(&p);
        printf("dist3 %08x %08x %08x -> %08x\n", (unsigned)fb(p.x),
               (unsigned)fb(p.y), (unsigned)fb(p.z),
               (unsigned)fb(world_get_distance_to_closest_player(&world,
                                                                 &p)));
        break;
    }
    case OP_RAW: {
        uint32_t k = next();
        uint32_t w = next();
        uint32_t p = next();
        Collision *c;

        printf("raw R%u W%u P%d\n", (unsigned)k, (unsigned)w, (int)p - 1);
        memset(&raw[k], 0xa5, sizeof raw[k]);
        c = collision_construct(&raw[k], &witnesses[w],
                                p != 0 ? &pts[p - 1] : NULL);
        if (nhandles == 4096) {
            fprintf(stderr, "too many handles\n");
            exit(2);
        }
        handles[nhandles++] = c;
        printf("  -> %s\n", label(c));
        dump(c);
        break;
    }
    case OP_DIST2: {
        bVector2 p;

        p.x = as_float(next());
        p.y = as_float(next());
        printf("dist2 %08x %08x -> %08x\n", (unsigned)fb(p.x),
               (unsigned)fb(p.y),
               (unsigned)fb(world_get_distance_to_closest_player_2d(&world,
                                                                    &p)));
        break;
    }
    default:
        fprintf(stderr, "op %u\n", (unsigned)op);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    unsigned int op;
    int i;

    if (argc != 2 || (script = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: collision_test SCRIPT\n");
        return 2;
    }
    bSlotPoolManagerInit();
    bSetSlotPoolAllocator(arena_alloc, arena_release);
    bSetSlotPoolPrintf(printf_hook);
    install_vtable();
    for (i = 0; i < NB; i++) {
        bodies[i] = calloc(1, sizeof(CarCollisionBody));
        bodies[i]->Dynamic.Body._vtable = FAKE_VT;
    }
    for (i = 0; i < NCAR; i++)
        cars[i] = calloc(1, sizeof(struct Car));
    world.CollisionList.next = &world.CollisionList;
    world.CollisionList.prev = &world.CollisionList;
    pCurrentWorld = &world;
    pTerrainEffectEmitters = &tee;
    gCollisionSoundCreateSampleFn = seam_create;
    gCollisionSoundReleaseSampleFn = seam_release;
    gCollisionSoundPlayScrapeFn = seam_scrape;
    gTerrainEffectTriggerFn = seam_trigger;

    while (fscanf(script, "%x", &op) == 1)
        step((uint32_t)op);
    fflush(stdout);
    return 0;
}
