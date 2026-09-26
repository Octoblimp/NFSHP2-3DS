// world_test -- the harness tools/world_check.py runs against World.obj's
// clock, car table, checksums and step: 3DS Files/source/worldstep.c, with
// world.c's distances and blist.c's sort.
//
// It reads a script of hex words from argv[1], one op and its operands at a
// time (the checker has the list), and prints what the model prints for the
// image. The labels are the checker's: CAR0..CAR13 the cars and DI0..DI13
// their DriverInfos, P0 and P1 the players, B0..B7 the bodies (Smokeables,
// so a smokeable's BreakingStrength is where DoTimestepCollisions reads
// it, on one recording vtable whose Move takes `this` eight bytes in),
// W0..W7 the witnesses, K0..K11 the contacts, C0..C3 the collisions; cars,
// bodies, witnesses and collisions the four list heads; TPM, FX, RM, RC,
// RACE, TT and HELI the track path manager, the effects, the replay
// manager, the race coordinator, the race, the teleporter and the
// helicopter; CB the time scale's callback; and local anything else, which
// is the port's stack. Every function the step calls outside worldstep.c
// is this file's, and logs.
//
//     world_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "blist.h"
#include "bticker.h"
#include "car.h"
#include "collision.h"
#include "collisionbody.h"
#include "joylog.h"
#include "player.h"
#include "race.h"
#include "realtime.h"
#include "replay.h"
#include "smokeable.h"
#include "trackpath.h"
#include "vtable.h"
#include "world.h"

enum {
    OP_TAG = 1, OP_CAR, OP_CARLIST, OP_PLAYER, OP_BUILD, OP_BYNUM, OP_BYDRV,
    OP_FLIP, OP_SORT, OP_TRAFFIC, OP_SCALE, OP_RESET, OP_PAUSE, OP_BEGIN,
    OP_END, OP_UPDPAUSE, OP_ISPAUSED, OP_TWEAK, OP_REALTIME, OP_REPLAY,
    OP_RGET, OP_JGET, OP_JFLAG, OP_TICKS, OP_TIMESTEP, OP_SEED, OP_RANDI,
    OP_RANDF, OP_DATS, OP_CMPQ, OP_DAT, OP_TIMER, OP_CHECKSUM, OP_VERIFY,
    OP_LOOP, OP_BODY, OP_BODYLIST, OP_MOVE, OP_WIT, OP_WITLIST, OP_CREATEQ,
    OP_CONTACT, OP_TESTQ, OP_BREAKQ, OP_COL, OP_COLLIST, OP_COLLIDE,
    OP_STATE, OP_RC, OP_PTRS, OP_STEP, OP_FLUSH, OP_PPOS, OP_DRAIN,
    OP_SHAKEFLIP,
};

#define NCAR 14
#define NB   8
#define NW   8
#define NK   12
#define NC   4

#define FAKE_VT 0x01F00000u
#define DELTA   8

// collisionbody.c's and trackpath.c's; the harness links neither.
CollisionBodyNode        CollisionBodyList;
CollisionBodyWitnessNode CollisionBodyWitnessList;
TrackPathManager         TheTrackPathManager;

static FILE *script;

static World world;
static struct Car *cars[NCAR];
static DriverInfo dis[NCAR];
static struct Player players[2];
static _Alignas(16) Smokeable bodies[NB];
static _Alignas(16) CollisionBodyWitness wits[NW];
static _Alignas(16) Contact contacts[NK];
static _Alignas(16) Collision cols[NC];
static ReplayManager rm;
static int32_t rc_obj[4];
static int32_t shake_flip = -1;     // the state MaybeCameraShake moves to
static int32_t race_obj[4];
static int32_t tele_obj[4];
static int32_t heli_obj[4];
static int fx_obj;
static int joylog_repeat;

static uint32_t csum[NCAR];
static int32_t vfx[NCAR];
static int32_t expired[NW];
static int32_t update_v[NC];

// The queues. Each is a ring the script fills and the stubs empty.
#define QN 8192
typedef struct Queue {
    uint32_t v[QN];
    int head, tail;
} Queue;

static Queue createq, testq, rgetq, jgetq, cmpq, tickq, placeq;
static struct {
    int n[QN];
    int k[QN][NB];
    int head, tail;
} breakq;
static uint32_t last_tick;

static void push(Queue *q, uint32_t v)
{
    q->v[q->tail++ % QN] = v;
}

static int pop(Queue *q, uint32_t *v)
{
    if (q->head == q->tail)
        return 0;
    *v = q->v[q->head++ % QN];
    return 1;
}

static void drain(void)
{
    createq.head = createq.tail = 0;
    testq.head = testq.tail = 0;
    rgetq.head = rgetq.tail = 0;
    jgetq.head = jgetq.tail = 0;
    cmpq.head = cmpq.tail = 0;
    tickq.head = tickq.tail = 0;
    placeq.head = placeq.tail = 0;
    breakq.head = breakq.tail = 0;
    shake_flip = -1;
}

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

// ------------------------------------------------------------ the labels

#define BODY_HEAD ((const void *)&CollisionBodyList)
#define WIT_HEAD  ((const void *)&CollisionBodyWitnessList)

static void cb(int32_t param);

static const char *label(const void *p)
{
    static char buf[8][32];
    static int k;
    char *b = buf[k++ & 7];
    int i;

    if (p == NULL)
        return "null";
    if (p == (const void *)&world.CarList)
        return "cars";
    if (p == (const void *)&world.CollisionList)
        return "collisions";
    if (p == BODY_HEAD)
        return "bodies";
    if (p == WIT_HEAD)
        return "witnesses";
    if (p == (const void *)&TheTrackPathManager)
        return "TPM";
    if (p == (const void *)&fx_obj)
        return "FX";
    if (p == (const void *)&rm)
        return "RM";
    if (p == (const void *)rc_obj)
        return "RC";
    if (p == (const void *)race_obj)
        return "RACE";
    if (p == (const void *)tele_obj)
        return "TT";
    if (p == (const void *)heli_obj)
        return "HELI";
    if (p == (const void *)(uintptr_t)cb)
        return "CB";
    for (i = 0; i < NCAR; i++) {
        if (p == (const void *)cars[i]) {
            snprintf(b, 32, "CAR%d", i);
            return b;
        }
        if (p == (const void *)&dis[i]) {
            snprintf(b, 32, "DI%d", i);
            return b;
        }
    }
    for (i = 0; i < 2; i++)
        if (p == (const void *)&players[i]) {
            snprintf(b, 32, "P%d", i);
            return b;
        }
    for (i = 0; i < NB; i++)
        if (p == (const void *)&bodies[i]) {
            snprintf(b, 32, "B%d", i);
            return b;
        }
    for (i = 0; i < NW; i++)
        if (p == (const void *)&wits[i]) {
            snprintf(b, 32, "W%d", i);
            return b;
        }
    for (i = 0; i < NK; i++)
        if (p == (const void *)&contacts[i]) {
            snprintf(b, 32, "K%d", i);
            return b;
        }
    for (i = 0; i < NC; i++)
        if (p == (const void *)&cols[i]) {
            snprintf(b, 32, "C%d", i);
            return b;
        }
    return "local";
}

static int car_of(const struct Car *c)
{
    int i;

    for (i = 0; i < NCAR; i++)
        if (c == cars[i])
            return i;
    fprintf(stderr, "not a car\n");
    exit(3);
}

// ------------------------------------------------------------- the stubs

static void cb(int32_t param)
{
    printf("  callback %d\n", param);
}

void car_think(struct Car *c, float dt)
{
    printf("  think %s %08x\n", label(c), fb(dt));
}

void car_drive(struct Car *c, float dt)
{
    printf("  drive %s %08x\n", label(c), fb(dt));
}

void car_begin_movement(struct Car *c, float dt)
{
    printf("  begin %s %08x\n", label(c), fb(dt));
}

int32_t car_should_visual_effects_be_generated(struct Car *c)
{
    int k = car_of(c);

    printf("  vfx %s -> %d\n", label(c), vfx[k]);
    return vfx[k];
}

void car_trigger_car_terrain_effects(struct Car *c, float distance)
{
    printf("  terrain %s %08x\n", label(c), fb(distance));
}

void car_fake_engine_task(struct Car *c)
{
    printf("  engine %s\n", label(c));
}

int32_t car_calculate_debug_checksum(struct Car *c)
{
    int k = car_of(c);

    printf("  checksum %s -> %08x\n", label(c), csum[k]);
    return (int32_t)csum[k];
}

static void seam_finish(struct Car *c, float dt)
{
    printf("  finish %s %08x\n", label(c), fb(dt));
}

static void seam_wheels(struct Car *c)
{
    printf("  wheels %s\n", label(c));
}

static void seam_events(struct Car *c)
{
    printf("  events %s\n", label(c));
}

static void seam_shake(struct Car *c)
{
    printf("  shake %s\n", label(c));
    if (shake_flip >= 0)
        rc_obj[0] = shake_flip;
}

static void seam_rumble(struct Car *c)
{
    printf("  rumble %s\n", label(c));
}

static void seam_teleport(struct TrafficTeleporter *t, float dt)
{
    printf("  teleport %s %08x\n", label(t), fb(dt));
}

static struct Car *seam_place(struct TrafficTeleporter *t, DriverInfo *info)
{
    uint32_t k = 0xFFFFFFFFu;
    struct Car *c;

    (void)pop(&placeq, &k);
    c = (int32_t)k >= 0 ? cars[k] : NULL;
    printf("  place %s %s -> %s\n", label(t), label(info), label(c));
    return c;
}

static void seam_copthink(float dt)
{
    printf("  copthink %08x\n", fb(dt));
}

static void seam_fly(struct Chopper *h, float dt)
{
    printf("  fly %s %08x\n", label(h), fb(dt));
}

static void seam_particles(void)
{
    printf("  particles\n");
}

static void seam_fxcheck(void)
{
    printf("  fxcheck %s\n", label(&fx_obj));
}

static void seam_fxstep(float dt)
{
    printf("  fxstep %s %08x\n", label(&fx_obj), fb(dt));
}

static void seam_emevents(void)
{
    printf("  emevents\n");
}

static void seam_gamestate(void)
{
    printf("  gamestate\n");
}

static void seam_rain(float dt)
{
    printf("  rain %08x\n", fb(dt));
}

static void seam_ferns(void)
{
    printf("  ferns\n");
}

static void seam_tweakdamage(void)
{
    printf("  tweakdamage\n");
}

static void seam_routeeditor(void)
{
    printf("  routeeditor\n");
}

static void seam_race(struct Race *r)
{
    printf("  race %s\n", label(r));
}

static void seam_post(struct RaceCoordinator *rc, int32_t msg, int32_t param)
{
    printf("  post %s %d %d\n", label(rc), msg, param);
}

static int32_t seam_jget(int32_t bits, int32_t channel)
{
    uint32_t v = 0;

    (void)pop(&jgetq, &v);
    printf("  jget %d %d -> %08x\n", bits, channel, v);
    return (int32_t)v;
}

static void seam_jadd(int32_t value, int32_t bits, int32_t channel)
{
    printf("  jadd %08x %d %d\n", (uint32_t)value, bits, channel);
}

static int32_t seam_rget(ReplayManager *m, int32_t bits, int32_t channel)
{
    uint32_t v = 0;

    (void)pop(&rgetq, &v);
    printf("  rget %s %d %d -> %08x\n", label(m), bits, channel, v);
    return (int32_t)v;
}

static void seam_radd(ReplayManager *m, int32_t value, int32_t bits,
                      int32_t channel)
{
    printf("  radd %s %08x %d %d\n", label(m), (uint32_t)value, bits,
           channel);
}

float trackpath_compare_distances(const TrackPathManager *m, float a, float b)
{
    uint32_t v = 0;

    (void)pop(&cmpq, &v);
    printf("  compare %s %08x %08x -> %08x\n", label(m), fb(a), fb(b), v);
    return as_float(v);
}

static uint32_t ticker(void)
{
    uint32_t v;

    if (!pop(&tickq, &v))
        v = last_tick + 0x40000000u;
    last_tick = v;
    printf("  ticker -> %08x\n", v);
    return v;
}

static void seam_farsmoke(void)
{
    printf("  farsmoke\n");
}

static void move(void *self, float dt)
{
    const char *p = (const char *)self - DELTA;
    int i;

    for (i = 0; i < NB; i++)
        if (p == (const char *)&bodies[i]) {
            printf("  move B%d %08x\n", i, fb(dt));
            return;
        }
    fprintf(stderr, "a slot called on a stranger\n");
    exit(3);
}

static void unlink_node(void *p)
{
    void **n = p;
    void **nx = n[0];
    void **pv = n[1];

    pv[0] = nx;
    nx[1] = pv;
}

// A destroyed node is freed in the game: its links are poisoned so a loop
// that reads them afterwards crashes.
static void kill_node(void *p)
{
    void **n = p;

    unlink_node(p);
    n[0] = NULL;
    n[1] = NULL;
}

static void append_node(void *head, void *p)
{
    void **h = head;
    void **n = p;
    void **tail = h[1];

    tail[0] = n;
    n[1] = tail;
    n[0] = h;
    h[1] = n;
}

static int on_list(const void *head, const void *p)
{
    void *const *q = ((void *const *)head)[0];
    int n = 0;

    for (; (const void *)q != head && n < 64; q = q[0], n++)
        if ((const void *)q == p)
            return 1;
    return 0;
}

void collisionbody_maybe_print_all(void)
{
    printf("  printall\n");
}

int32_t cbwitness_has_expired(CollisionBodyWitness *w)
{
    int k = (int)(w - wits);

    printf("  expired %s -> %d\n", label(w), expired[k]);
    return expired[k];
}

void cbwitness_destroy(CollisionBodyWitness *w, int32_t flags)
{
    printf("  destroy witness %s %d\n", label(w), flags);
    kill_node(w);
}

void dynamiccollisionbody_maybe_create_witnesses(DynamicCollisionBody *d)
{
    uint32_t k = 0xFFFFFFFFu;
    CollisionBodyWitness *w;

    (void)pop(&createq, &k);
    w = (int32_t)k >= 0 ? &wits[k] : NULL;
    if (w != NULL && on_list(&CollisionBodyWitnessList, w))
        w = NULL;
    printf("  create %s -> %s\n", label(d), label(w));
    if (w != NULL)
        append_node(&CollisionBodyWitnessList, w);
}

void cbwitness_test_for_contact(CollisionBodyWitness *w, ContactNode *list)
{
    uint32_t k = 0xFFFFFFFFu;
    Contact *c;

    (void)pop(&testq, &k);
    c = (int32_t)k >= 0 ? &contacts[k] : NULL;
    if (c != NULL && on_list(list, c))
        c = NULL;
    printf("  test %s %s -> %s\n", label(w), label(list), label(c));
    if (c != NULL)
        append_node(list, c);
}

void contact_resolve(Contact *c)
{
    printf("  resolve %s\n", label(c));
}

void contact_remove_contacts(ContactNode *list, CollisionBody *b)
{
    Contact *c = list->next;

    printf("  remove %s %s:", label(list), label(b));
    while ((void *)c != (void *)list) {
        Contact *nx = c->Link.next;

        if (c->pBody1 == b || c->pBody2 == b) {
            unlink_node(c);
            printf(" %s", label(c));
        }
        c = nx;
    }
    printf("\n");
}

static int32_t seam_break(Smokeable *s, DynamicCollisionBody **pieces)
{
    int i, n = 0;

    printf("  break %s ->", label(s));
    if (breakq.head != breakq.tail) {
        int j = breakq.head++ % QN;

        n = breakq.n[j];
        for (i = 0; i < n; i++) {
            pieces[i] = &bodies[breakq.k[j][i]].Dynamic;
            printf(" B%d", breakq.k[j][i]);
        }
    }
    printf("\n");
    return n;
}

void contact_destroy(Contact *c, int32_t flags)
{
    printf("  destroy contact %s %d\n", label(c), flags);
}

int32_t collision_update(Collision *c, float dt)
{
    int k = (int)(c - cols);

    printf("  update %s %08x -> %d\n", label(c), fb(dt), update_v[k]);
    return update_v[k];
}

void collision_end(Collision *c)
{
    printf("  end %s\n", label(c));
    kill_node(c);
}

// ------------------------------------------------------------ the dumps

static void walk(const void *head, const char *name)
{
    void *const *p;
    int n;

    printf("  %s fwd", name);
    for (p = ((void *const *)head)[0], n = 0; (const void *)p != head && n < 40;
         p = p[0], n++)
        printf(" %s", label(p));
    printf(" back");
    for (p = ((void *const *)head)[1], n = 0; (const void *)p != head && n < 40;
         p = p[1], n++)
        printf(" %s", label(p));
    printf("\n");
}

static void state(void)
{
    int j;

    printf("  state pause %08x waste %08x scale %08x timer %08x cb %s"
           " param %d seed %08x\n",
           fb(world.fTimeToRemainPaused), fb(world.PreviousTimeToWaste),
           fb(world.fTimeScale), fb(world.fTimeScaleTimer),
           label((const void *)(uintptr_t)world.TimeScaleCallback),
           world.TimeScaleCallbackParam, world.WorldRandomSeed);
    printf("  players");
    for (j = 0; j < 2; j++)
        printf(" %08x %08x %08x %08x", fb(world.PlayerPositions[j].x),
               fb(world.PlayerPositions[j].y), fb(world.PlayerPositions[j].z),
               fb(world.PlayerPositions[j].pad));
    printf(" dat %08x %08x\n", fb(world.PlayerDATs[0]),
           fb(world.PlayerDATs[1]));
}

static void table(void)
{
    int n = world.TotalNumCars;
    int i;

    printf("  table n %d ai %d cop %d traffic %d:", n, world.AICarPos,
           world.CopCarPos, world.TrafficCarPos);
    for (i = 0; i < n && i < NCAR; i++)
        printf(" %s", label(world.CarTable[i]));
    printf("\n  index");
    for (i = 0; i < NCAR; i++)
        printf(" %d", cars[i]->CarIndex);
    printf("\n");
}

static void postable(void)
{
    int n = world.TotalNumCars;
    int i;

    for (i = 0; i < n && i < NCAR; i++)
        printf("  pos %d %08x %08x %08x %08x\n", i,
               fb(world.CarPositionTable[i].x),
               fb(world.CarPositionTable[i].y),
               fb(world.CarPositionTable[i].z),
               fb(world.CarPositionTable[i].pad));
}

static void relink(void *head, void *objs, size_t size, int n)
{
    void **h = head;
    int i;

    h[0] = h;
    h[1] = h;
    for (i = 0; i < n; i++)
        append_node(head, (char *)objs + size * next());
}

static void relink_cars(int n)
{
    void **h = (void **)&world.CarList;
    int i;

    h[0] = h;
    h[1] = h;
    for (i = 0; i < n; i++)
        append_node(h, cars[next()]);
}

static int32_t in_order(bNode *a, bNode *b)
{
    return world_car_list_check_flip((struct Car *)(void *)a,
                                     (struct Car *)(void *)b);
}

// ------------------------------------------------------------- the ops

static void (*pick_cb(uint32_t v))(int32_t)
{
    return v ? cb : NULL;
}

static void step(uint32_t op)
{
    uint32_t a, b, c, d;
    int i;

    switch (op) {
    case OP_TAG:
        printf("[%u]\n", next());
        break;
    case OP_DRAIN:
        drain();
        break;
    case OP_CAR: {
        struct Car *car;

        a = next();
        car = cars[a];
        dis[a].TheDriverType = (DriverType)next();
        car->DriverNumber = (int16_t)next();
        car->State.Position.x = as_float(next());
        car->State.Position.y = as_float(next());
        car->State.Position.z = as_float(next());
        car->State.Position.pad = as_float(next());
        car->TheTrackPathCoordinate.DistanceAroundTrack = as_float(next());
        csum[a] = next();
        vfx[a] = (int32_t)next();
        printf("car CAR%u\n", a);
        break;
    }
    case OP_CARLIST:
        relink_cars((int)next());
        printf("carlist\n");
        walk(&world.CarList, "cars");
        break;
    case OP_PLAYER:
        a = next();
        b = next();
        if ((int32_t)b < 0) {
            PlayerPlayersByNumber[a] = NULL;
        } else {
            PlayerPlayersByNumber[a] = &players[a];
            players[a].MyCar = cars[b];
        }
        printf("player %u %d\n", a, (int32_t)b);
        break;
    case OP_BUILD:
        printf("build\n");
        world_build_car_table(&world);
        table();
        break;
    case OP_BYNUM:
        a = next();
        printf("bynum %d -> %s\n", (int32_t)a,
               label(world_get_car_by_number(&world, (int32_t)a)));
        break;
    case OP_BYDRV:
        a = next();
        printf("bydrv %d -> %s\n", (int32_t)a,
               label(world_get_car_by_driver_number((int32_t)a)));
        break;
    case OP_FLIP:
        a = next();
        b = next();
        printf("flip CAR%u CAR%u -> %d\n", a, b,
               world_car_list_check_flip(cars[a], cars[b]));
        break;
    case OP_SORT:
        printf("sort\n");
        blist_sort((bNode *)(void *)&world.CarList, in_order);
        walk(&world.CarList, "cars");
        break;
    case OP_TRAFFIC:
        a = next();
        push(&placeq, next());
        printf("traffic DI%u\n", a);
        world_add_traffic_car(&world, &dis[a]);
        walk(&world.CarList, "cars");
        break;
    case OP_SCALE:
        a = next();
        b = next();
        c = next();
        d = next();
        printf("scale\n");
        world_set_time_scale(&world, as_float(a), as_float(b), pick_cb(c),
                             (int32_t)d);
        state();
        break;
    case OP_RESET:
        printf("reset\n");
        world_reset_time_scale(&world);
        state();
        break;
    case OP_PAUSE:
        a = next();
        b = next();
        c = next();
        printf("pause\n");
        world_set_world_paused(&world, as_float(a), pick_cb(b), (int32_t)c);
        state();
        break;
    case OP_BEGIN:
        printf("begin\n");
        world_begin_pause(&world);
        state();
        break;
    case OP_END:
        printf("end\n");
        world_end_pause(&world);
        state();
        break;
    case OP_UPDPAUSE:
        printf("updpause\n");
        world_update_world_paused(&world);
        state();
        break;
    case OP_ISPAUSED:
        printf("ispaused -> %d\n", world_is_world_paused(&world));
        break;
    case OP_TWEAK:
        TweakerPauseWorld = (int32_t)next();
        printf("tweak %d\n", TweakerPauseWorld);
        break;
    case OP_REALTIME:
        a = next();
        b = next();
        RealTimeElapsed = as_float(a);
        RealTimeElapsedQuantized = (int32_t)b;
        printf("realtime %08x %d\n", a, (int32_t)b);
        break;
    case OP_REPLAY:
        rm.ReplayingFlag = (int32_t)next();
        rm.CapturingFlag = (int32_t)next();
        printf("replay %d %d\n", rm.ReplayingFlag, rm.CapturingFlag);
        break;
    case OP_RGET:
        push(&rgetq, next());
        break;
    case OP_JGET:
        push(&jgetq, next());
        break;
    case OP_JFLAG:
        Joylog_ReplayingFlag = (int32_t)next();
        printf("jflag %d\n", Joylog_ReplayingFlag);
        break;
    case OP_TICKS:
        a = next();
        for (i = 0; i < (int)a; i++)
            push(&tickq, next());
        break;
    case OP_TIMESTEP: {
        float r;

        printf("timestep\n");
        r = world_get_timestep(&world);
        printf("  -> %08x\n", fb(r));
        state();
        break;
    }
    case OP_SEED:
        world.WorldRandomSeed = next();
        printf("seed %08x\n", world.WorldRandomSeed);
        break;
    case OP_RANDI: {
        int32_t v;

        a = next();
        v = world_random_i(&world, (int32_t)a);
        printf("randi %d -> %d seed %08x\n", (int32_t)a, v,
               world.WorldRandomSeed);
        break;
    }
    case OP_RANDF: {
        float v;

        a = next();
        v = world_random_f(&world, as_float(a));
        printf("randf %08x -> %08x seed %08x\n", a, fb(v),
               world.WorldRandomSeed);
        break;
    }
    case OP_DATS:
        a = next();
        b = next();
        world.PlayerDATs[0] = as_float(a);
        world.PlayerDATs[1] = as_float(b);
        printf("dats %08x %08x\n", a, b);
        break;
    case OP_CMPQ:
        push(&cmpq, next());
        break;
    case OP_DAT: {
        float r;

        a = next();
        printf("dat %08x\n", a);
        r = world_get_dat_to_closest_player(&world, as_float(a));
        printf("  -> %08x\n", fb(r));
        break;
    }
    case OP_TIMER:
        WorldTimer = (int32_t)next();
        printf("timer %08x\n", (uint32_t)WorldTimer);
        break;
    case OP_CHECKSUM: {
        uint32_t v;

        printf("checksum\n");
        v = world_calculate_debug_checksum(&world);
        printf("  -> %08x\n", v);
        postable();
        break;
    }
    case OP_VERIFY:
        printf("verify\n");
        world_verify_debug_checksums(&world);
        break;
    case OP_LOOP:
        WorldLoopCounter = (int32_t)next();
        printf("loop %08x\n", (uint32_t)WorldLoopCounter);
        break;
    case OP_BODY: {
        CollisionBody *body;

        a = next();
        body = &bodies[a].Dynamic.Body;
        body->Type = (int8_t)next();
        body->Dynamic = (int8_t)next();
        body->ActiveCollisionDetection = (int8_t)next();
        bodies[a].BreakingStrength = as_float(next());
        printf("body B%u\n", a);
        break;
    }
    case OP_BODYLIST:
        relink(&CollisionBodyList, bodies, sizeof bodies[0], (int)next());
        printf("bodylist\n");
        walk(BODY_HEAD, "bodies");
        break;
    case OP_MOVE:
        a = next();
        printf("move %08x\n", a);
        world_do_timestep_move(&world, as_float(a));
        break;
    case OP_WIT:
        a = next();
        wits[a].pBody1 = &bodies[next()].Dynamic.Body;
        wits[a].pBody2 = &bodies[next()].Dynamic.Body;
        expired[a] = (int32_t)next();
        printf("wit W%u\n", a);
        break;
    case OP_WITLIST:
        relink(&CollisionBodyWitnessList, wits, sizeof wits[0], (int)next());
        printf("witlist\n");
        walk(WIT_HEAD, "witnesses");
        break;
    case OP_CREATEQ:
        push(&createq, next());
        break;
    case OP_CONTACT:
        a = next();
        contacts[a].pBody1 = &bodies[next()].Dynamic.Body;
        contacts[a].pBody2 = &bodies[next()].Dynamic.Body;
        printf("contact K%u\n", a);
        break;
    case OP_TESTQ:
        push(&testq, next());
        break;
    case OP_BREAKQ: {
        int j = breakq.tail++ % QN;

        breakq.n[j] = (int)next();
        for (i = 0; i < breakq.n[j]; i++)
            breakq.k[j][i] = (int)next();
        break;
    }
    case OP_COL:
        a = next();
        update_v[a] = (int32_t)next();
        printf("col C%u\n", a);
        break;
    case OP_COLLIST:
        relink(&world.CollisionList, cols, sizeof cols[0], (int)next());
        printf("collist\n");
        walk(&world.CollisionList, "collisions");
        break;
    case OP_COLLIDE:
        a = next();
        printf("collide %08x\n", a);
        world_do_timestep_collisions(&world, as_float(a));
        walk(WIT_HEAD, "witnesses");
        walk(&world.CollisionList, "collisions");
        break;
    case OP_STATE:
        printf("state\n");
        state();
        break;
    case OP_SHAKEFLIP:
        shake_flip = (int32_t)next();
        printf("shakeflip %d\n", shake_flip);
        break;
    case OP_RC:
        rc_obj[0] = (int32_t)next();
        printf("rc %d\n", rc_obj[0]);
        break;
    case OP_PTRS:
        a = next();
        b = next();
        c = next();
        world.Teleporter = a ? (struct TrafficTeleporter *)(void *)tele_obj
                             : NULL;
        world.Helicopter = b ? (struct Chopper *)(void *)heli_obj : NULL;
        pCurrentRace = c ? (Race *)(void *)race_obj : NULL;
        printf("ptrs %u %u %u\n", a, b, c);
        break;
    case OP_STEP:
        a = next();
        printf("step %08x\n", a);
        world_do_timestep(&world, as_float(a));
        state();
        walk(&world.CarList, "cars");
        walk(WIT_HEAD, "witnesses");
        walk(&world.CollisionList, "collisions");
        postable();
        break;
    case OP_FLUSH:
        printf("flush\n");
        world_flush_collisions(&world);
        break;
    case OP_PPOS:
        a = next();
        world.PlayerPositions[a].x = as_float(next());
        world.PlayerPositions[a].y = as_float(next());
        world.PlayerPositions[a].z = as_float(next());
        world.PlayerPositions[a].pad = as_float(next());
        world.PlayerDATs[a] = as_float(next());
        printf("ppos %u\n", a);
        break;
    default:
        fprintf(stderr, "op %u\n", op);
        exit(2);
    }
}

static void install_vtable(void)
{
    static VtEntry vt[COLLISIONBODY_VT_ENTRIES];

    vt[VT_SLOT(COLLISIONBODY_VT_MOVE)].delta = DELTA;
    vt[VT_SLOT(COLLISIONBODY_VT_MOVE)].fn = (VtFn)move;
    vt_install(FAKE_VT, vt, COLLISIONBODY_VT_ENTRIES);
}

int main(int argc, char **argv)
{
    unsigned int op;
    int i;

    if (argc != 2 || (script = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: world_test SCRIPT\n");
        return 2;
    }
    install_vtable();
    for (i = 0; i < NCAR; i++) {
        cars[i] = calloc(1, sizeof(struct Car));
        cars[i]->MyDriver = &dis[i];
    }
    for (i = 0; i < NB; i++)
        bodies[i].Dynamic.Body._vtable = FAKE_VT;
    world.CarList.next = world.CarList.prev = &world.CarList;
    world.CollisionList.next = world.CollisionList.prev = &world.CollisionList;
    CollisionBodyList.next = CollisionBodyList.prev =
        (CollisionBody *)(void *)&CollisionBodyList;
    CollisionBodyWitnessList.next = CollisionBodyWitnessList.prev =
        (CollisionBodyWitness *)(void *)&CollisionBodyWitnessList;
    world.fTimeScale = 1.0f;
    pCurrentWorld = &world;
    pReplayManager = &rm;
    pRaceCoordinator = (RaceCoordinator *)(void *)rc_obj;

    gReplayManagerGetData = seam_rget;
    gReplayManagerAddData = seam_radd;
    Joylog_pRepeat = &joylog_repeat;
    Joylog_CapturingFlag = 1;
    gJoylogRepeatGetData = seam_jget;
    gJoylogRepeatAddData = seam_jadd;
    bSetTickerSource(ticker);

    gTrafficTeleporterDoTimestepFn = seam_teleport;
    gTrafficTeleporterPlaceNewCarFn = seam_place;
    gGlobalCopThinkFn = seam_copthink;
    gCarDoWheelForcesFn = seam_wheels;
    gChopperFlyFn = seam_fly;
    gCarFinishMovementFn = seam_finish;
    gCarTriggerEventsFn = seam_events;
    gCarMaybeCameraShakeFn = seam_shake;
    gCarMaybeRumbleFn = seam_rumble;
    gServiceParticleGroupsFn = seam_particles;
    gWorldEffectsTweakerCheckFn = seam_fxcheck;
    gWorldEffectsDoTimeStepFn = seam_fxstep;
    gEmProcessAllEventsFn = seam_emevents;
    gUpdatePlayersGameStateFn = seam_gamestate;
    gRainTimeStepFn = seam_rain;
    gServiceFernFlattenersFn = seam_ferns;
    gServiceTweakerDamageFn = seam_tweakdamage;
    gServiceTrackRouteEditorFn = seam_routeeditor;
    gRaceUpdateFn = seam_race;
    gRaceCoordinatorPostMessageFn = seam_post;
    gSmokeableBreakFn = seam_break;
    gDeleteFarAwaySmokeableCollisionBodiesFn = seam_farsmoke;

    while (fscanf(script, "%x", &op) == 1)
        step((uint32_t)op);
    fflush(stdout);
    return 0;
}
