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
// World's constructor, destructor, prediction and debug views
// (worldinit.c), with obb.c and emath.c, add: ailist, the AI list's head;
// MY0..MY19 and OT0..OT19 the World's boxes, SM0..SM19 and SO0..SO19 the
// two arrays a script hands CollisionPredictionSetOBBs; DTM, DTO and DTP
// the World's drive targets, DTA and DTB two to copy in; WO0..WO127 the
// debug cubes (a new one is the next from 0, a script's from 64 up);
// PN0..PN7 the AI list's nodes; CTL0..CTL3 the controllers, on a second
// recording vtable whose DebugDisplay takes `this` eight bytes in, and
// DRV0..DRV13 the cars' drivers; MYPOS0..39 and OTPOS0..39 the recorded
// positions; DTR the drive target renderer; TTMEM the teleporter's
// memory; and dirty a pointer still holding the 0xA5 fill.
//
//     world_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "blist.h"
#include "bmath.h"
#include "bmem.h"
#include "bplist.h"
#include "bticker.h"
#include "car.h"
#include "carcontroller.h"
#include "collision.h"
#include "collisionbody.h"
#include "drivetargetrenderer.h"
#include "joylog.h"
#include "player.h"
#include "race.h"
#include "realtime.h"
#include "replay.h"
#include "smokeable.h"
#include "topology.h"
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
    OP_SHAKEFLIP, OP_WFILL, OP_WCTOR, OP_WDTOR, OP_WDUMP, OP_AILIST, OP_OBB,
    OP_OBBDUMP, OP_OBBASSIGN, OP_OBBRENDER, OP_OBBHIDE, OP_OBBINIT,
    OP_OBBDTOR, OP_SETOBBS, OP_SETDTS, OP_RECPOT, OP_RECITER, OP_PREDDUMP,
    OP_CTL, OP_SETTABLE, OP_DDSET, OP_DEBUGDISP, OP_AITWEAK, OP_AIDEBUG,
    OP_CUBES, OP_CUBE, OP_DSEED, OP_CLOCK, OP_VOTSET, OP_RMODE,
};

#define NCAR 14
#define NB   8
#define NW   8
#define NK   12
#define NC   4

#define FAKE_VT 0x01F00000u
#define DELTA   8

#define NP       8
#define NCUBE    128
#define NCTL     4
#define FAKE_VT2 0x01F00100u

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

// World's constructor and so on.
static _Alignas(16) OBB sm[WORLD_PREDICTION_OBBS];
static _Alignas(16) OBB so[WORLD_PREDICTION_OBBS];
static _Alignas(16) WorldObject cubes[NCUBE];
static int cube_dead[NCUBE];
static int next_cube;
static bPNode pnodes[NP];
static CarController ctls[NCTL];
static int32_t drv_obj[NCAR][4];
static DriveTarget dts[2];
static _Alignas(16) uint8_t ttmem[TRAFFICTELEPORTER_SIZE];
static int32_t dd_ai = -1, dd_cop = -1;    // what DebugDisplay moves to
static int32_t vot_set = -1;               // and GetVectorOnTrack
DriveTargetRenderer TheDriveTargetRenderer;

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
    next_cube = 0;
    dd_ai = dd_cop = -1;
    vot_set = -1;
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
    if (p == (const void *)&world.AICarList)
        return "ailist";
    if (p == (const void *)&world.CollisionPredictionMyDriveTarget)
        return "DTM";
    if (p == (const void *)&world.CollisionPredictionOtherCarDriveTarget)
        return "DTO";
    if (p == (const void *)&world.PotentialDriveTarget)
        return "DTP";
    if (p == (const void *)&dts[0])
        return "DTA";
    if (p == (const void *)&dts[1])
        return "DTB";
    if (p == (const void *)&TheDriveTargetRenderer)
        return "DTR";
    if (p == (const void *)ttmem)
        return "TTMEM";
    {
        uintptr_t fill;

        memset(&fill, 0xA5, sizeof fill);
        if ((uintptr_t)p == fill)
            return "dirty";
    }
    for (i = 0; i < WORLD_PREDICTION_OBBS; i++) {
        const char *pre = NULL;

        if (p == (const void *)&world.CollisionPredictionMyOBBs[i])
            pre = "MY";
        else if (p == (const void *)&world.CollisionPredictionOtherCarOBBs[i])
            pre = "OT";
        else if (p == (const void *)&sm[i])
            pre = "SM";
        else if (p == (const void *)&so[i])
            pre = "SO";
        if (pre != NULL) {
            snprintf(b, 32, "%s%d", pre, i);
            return b;
        }
    }
    for (i = 0; i < WORLD_PREDICTION_ITERATIONS; i++) {
        if (p == (const void *)&world.CollisionPredictionMyPositions[i]) {
            snprintf(b, 32, "MYPOS%d", i);
            return b;
        }
        if (p == (const void *)&world.CollisionPredictionOtherCarPositions[i]) {
            snprintf(b, 32, "OTPOS%d", i);
            return b;
        }
    }
    for (i = 0; i < NCUBE; i++)
        if (p == (const void *)&cubes[i]) {
            snprintf(b, 32, "WO%d", i);
            return b;
        }
    for (i = 0; i < NP; i++)
        if (p == (const void *)&pnodes[i]) {
            snprintf(b, 32, "PN%d", i);
            return b;
        }
    for (i = 0; i < NCTL; i++)
        if (p == (const void *)&ctls[i]) {
            snprintf(b, 32, "CTL%d", i);
            return b;
        }
    for (i = 0; i < NCAR; i++)
        if (p == (const void *)drv_obj[i]) {
            snprintf(b, 32, "DRV%d", i);
            return b;
        }
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

void rain_TimeStep(float dt)
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

// ------------------------------------------- the constructor's stubs

#define LOGSEAM(fn, text) \
    static void fn(void) \
    { \
        printf("  " text "\n"); \
    }

LOGSEAM(seam_init_carfx, "init carfx")
LOGSEAM(seam_init_clans, "init clans")
LOGSEAM(seam_init_skids, "init skids")
LOGSEAM(seam_init_particles, "init particles")
LOGSEAM(seam_init_munitions, "init munitions")
LOGSEAM(seam_init_fernflat, "init fernflat")
LOGSEAM(seam_init_fernshake, "init fernshake")
LOGSEAM(seam_spawn_smokeables, "spawn smokeables")
LOGSEAM(seam_init_terrainfx, "init terrainfx")
LOGSEAM(seam_init_cops, "init cops")
LOGSEAM(seam_init_trackgraph, "init trackgraph")
LOGSEAM(seam_close_terrainfx, "close terrainfx")
LOGSEAM(seam_cleanup_cops, "cleanup cops")
LOGSEAM(seam_cleanup_trackgraph, "cleanup trackgraph")
LOGSEAM(seam_clear_smokeables, "clear smokeables")
LOGSEAM(seam_close_fernshake, "close fernshake")
LOGSEAM(seam_close_fernflat, "close fernflat")
LOGSEAM(seam_close_munitions, "close munitions")
LOGSEAM(seam_close_particles, "close particles")
LOGSEAM(seam_close_clans, "close clans")
LOGSEAM(seam_close_skids, "close skids")
LOGSEAM(seam_close_carfx, "close carfx")

void cbwitness_eliminate_all(void)
{
    printf("  eliminate witnesses\n");
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    printf("  malloc %d %s %d %d -> %s\n", size, name, flags, pool,
           label(ttmem));
    return ttmem;
}

void bFree(void *p)
{
    printf("  free %s\n", label(p));
}

static struct TrafficTeleporter *seam_tele_ctor(void *mem)
{
    printf("  teleporter ctor %s -> %s\n", label(mem), label(tele_obj));
    return (struct TrafficTeleporter *)(void *)tele_obj;
}

static void seam_tele_dtor(struct TrafficTeleporter *t, int32_t flags)
{
    printf("  teleporter dtor %s %d\n", label(t), flags);
}

// A list's destructor hands each node over unlinked from the list but with
// its own links as they were: they are printed, then poisoned.
static void gone(const char *what, void *p, int32_t flags)
{
    void **n = p;

    if (flags >= 0)
        printf("  %s %s %d links %s %s\n", what, label(p), flags,
               label(n[0]), label(n[1]));
    else
        printf("  %s %s links %s %s\n", what, label(p), label(n[0]),
               label(n[1]));
    n[0] = NULL;
    n[1] = NULL;
}

static void seam_car_destroy(struct Car *c, int32_t flags)
{
    gone("destroy car", c, flags);
}

void collision_destroy(Collision *c, int32_t flags)
{
    gone("destroy collision", c, flags);
}

void bpnode_free(void *p)
{
    gone("free pnode", p, -1);
}

DriveTarget *drivetarget_init(DriveTarget *t)
{
    printf("  dt init %s\n", label(t));
    return t;
}

void drivetarget_destroy(DriveTarget *t)
{
    printf("  dt destroy %s\n", label(t));
}

DriveTarget *drivetarget_assign(DriveTarget *dst, const DriveTarget *src)
{
    printf("  dt assign %s %s\n", label(dst), label(src));
    return dst;
}

void drivetargetrenderer_set_target_to_render(DriveTargetRenderer *r,
                                              DriveTarget *t)
{
    printf("  target %s %s\n", label(r), label(t));
}

// A point on the ground: the two lanes swapped and x negated in the third,
// so the two calls and the two lanes all show.
void get_vector_on_track(bVector3 *out, const bVector2 *in)
{
    printf("  vot %s %08x %08x\n", label(in), fb(in->x), fb(in->y));
    out->x = in->y;
    out->y = in->x;
    out->z = as_float(fb(in->x) ^ 0x80000000u);
    if (vot_set != -1) {
        WhichCollisionPredictionIterationToRender = vot_set;
        vot_set = -1;
    }
}

static void fresh_cube(int k)
{
    uint32_t *m = (uint32_t *)(void *)&cubes[k].Matrix;
    int j;

    cubes[k].Enabled = 7;
    for (j = 0; j < 16; j++)
        m[j] = 0x5A5A0000u + (uint32_t)(k << 4) + (uint32_t)j;
    cube_dead[k] = 0;
}

static WorldObject *seam_wo_new(uint32_t hash, const bMatrix4 *m,
                                int32_t light)
{
    int k = next_cube++;

    printf("  new cube %s hash %08x matrix %s light %d\n", label(&cubes[k]),
           hash, label(m), light);
    fresh_cube(k);
    return &cubes[k];
}

static void seam_wo_delete(WorldObject *o)
{
    printf("  delete cube %s 3\n", label(o));
    cube_dead[o - cubes] = 1;
}

static void debug_display(void *self)
{
    const char *p = (const char *)self - DELTA;
    int i;

    for (i = 0; i < NCTL; i++)
        if (p == (const char *)&ctls[i]) {
            printf("  debugdisplay CTL%d\n", i);
            if (dd_ai >= 0)
                world.AICarPos = dd_ai;
            if (dd_cop >= 0)
                world.CopCarPos = dd_cop;
            dd_ai = dd_cop = -1;
            return;
        }
    fprintf(stderr, "a debug display on a stranger\n");
    exit(3);
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

static void vec3(const bVector3 *v)
{
    printf(" %08x %08x %08x %08x", fb(v->x), fb(v->y), fb(v->z), fb(v->pad));
}

static void wdump(void)
{
    int k;

    walk(&world.CarList, "cars");
    walk(&world.AICarList, "ailist");
    walk(&world.CollisionList, "collisions");
    printf("  counts n %d ai %d cop %d traffic %d ids %u %u heli %s tele %s\n",
           world.TotalNumCars, world.AICarPos, world.CopCarPos,
           world.TrafficCarPos, world.CollisionPredictionID,
           world.PotentialDriveTargetID, label(world.Helicopter),
           label(world.Teleporter));
    state();
    printf("  globals world %s timer %08x secs %08x time %08x frames %08x"
           " elapsed %08x frame %08x loop %08x dseed %08x\n",
           label(pCurrentWorld), (uint32_t)WorldTimer, fb(WorldTimeSeconds),
           (uint32_t)WorldTime, (uint32_t)WorldTimeFrames,
           fb(WorldTimeElapsed), fb(WorldTimeElapsedFrame),
           (uint32_t)WorldLoopCounter, bDefaultSeed);
    printf("  untouched %s %s %08x %08x\n", label(world.CarTable[0]),
           label(world.CarTable[WORLD_MAX_CARS - 1]),
           fb(world.CarPositionTable[0].x),
           fb(world.CarPositionTable[WORLD_MAX_CARS - 1].pad));
    printf("  cubes MY");
    for (k = 0; k < WORLD_PREDICTION_OBBS; k++)
        printf(" %s", label(world.CollisionPredictionMyOBBs[k].WorldObj));
    printf(" OT");
    for (k = 0; k < WORLD_PREDICTION_OBBS; k++)
        printf(" %s", label(world.CollisionPredictionOtherCarOBBs[k].WorldObj));
    printf("\n");
}

static OBB *obb_at(uint32_t which, uint32_t k)
{
    switch (which) {
    case 0:
        return &world.CollisionPredictionMyOBBs[k];
    case 1:
        return &world.CollisionPredictionOtherCarOBBs[k];
    case 2:
        return &sm[k];
    default:
        return &so[k];
    }
}

static void obbline(const OBB *o)
{
    printf("  %s", label(o));
    vec3(&o->Position);
    vec3(&o->A0);
    vec3(&o->A1);
    vec3(&o->A2);
    printf(" %08x %08x %08x %s\n", fb(o->a0), fb(o->a1), fb(o->a2),
           label(o->WorldObj));
}

static void obbdump(uint32_t which)
{
    int k;

    for (k = 0; k < WORLD_PREDICTION_OBBS; k++)
        obbline(obb_at(which, (uint32_t)k));
}

static void iterline(int k)
{
    printf("  it %d %d %d %08x %08x %08x %08x\n", k,
           world.CollisionPredictionMyIndicies[k],
           world.CollisionPredictionOtherCarIndicies[k],
           fb(world.CollisionPredictionMyPositions[k].x),
           fb(world.CollisionPredictionMyPositions[k].y),
           fb(world.CollisionPredictionOtherCarPositions[k].x),
           fb(world.CollisionPredictionOtherCarPositions[k].y));
}

static void cubedump(int first, int n)
{
    int k, j;

    for (k = first; k < first + n; k++) {
        const uint32_t *m = (const uint32_t *)(const void *)&cubes[k].Matrix;

        printf("  WO%d %s en %d", k, cube_dead[k] ? "dead" : "live",
               cubes[k].Enabled);
        for (j = 0; j < 16; j++)
            printf(" %08x", m[j]);
        printf("\n");
    }
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
    case OP_RMODE:
        rm.PausedFlag = (int32_t)next();
        rm.SlowMotionFlag = (int32_t)next();
        printf("rmode %d %d\n", rm.PausedFlag, rm.SlowMotionFlag);
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
    case OP_WFILL:
        memset(&world, 0xA5, sizeof world);
        printf("wfill\n");
        break;
    case OP_WCTOR: {
        World *r;

        printf("wctor\n");
        r = world_init(&world);
        printf("  -> %s\n", label(r));
        wdump();
        break;
    }
    case OP_WDTOR:
        a = next();
        printf("wdtor %d\n", (int32_t)a);
        world_destroy(&world, (int32_t)a);
        wdump();
        break;
    case OP_WDUMP:
        printf("wdump\n");
        wdump();
        break;
    case OP_AILIST:
        relink(&world.AICarList, pnodes, sizeof pnodes[0], (int)next());
        printf("ailist\n");
        walk(&world.AICarList, "ailist");
        break;
    case OP_OBB: {
        OBB *o;
        bVector3 *v[4];
        int j;

        a = next();
        b = next();
        o = obb_at(a, b);
        v[0] = &o->Position;
        v[1] = &o->A0;
        v[2] = &o->A1;
        v[3] = &o->A2;
        for (j = 0; j < 4; j++) {
            v[j]->x = as_float(next());
            v[j]->y = as_float(next());
            v[j]->z = as_float(next());
            v[j]->pad = as_float(next());
        }
        o->a0 = as_float(next());
        o->a1 = as_float(next());
        o->a2 = as_float(next());
        c = next();
        o->WorldObj = (int32_t)c >= 0 ? &cubes[c] : NULL;
        printf("obb %s\n", label(o));
        break;
    }
    case OP_OBBDUMP:
        a = next();
        printf("obbdump %u\n", a);
        obbdump(a);
        break;
    case OP_OBBASSIGN: {
        OBB *dst, *src, *r;

        a = next();
        b = next();
        c = next();
        d = next();
        dst = obb_at(a, b);
        src = obb_at(c, d);
        printf("obbassign %s %s\n", label(dst), label(src));
        r = obb_assign(dst, src);
        printf("  -> %s\n", label(r));
        obbline(dst);
        obbline(src);
        break;
    }
    case OP_OBBRENDER: {
        OBB *o;
        bVector3 p;

        a = next();
        b = next();
        o = obb_at(a, b);
        p.x = as_float(next());
        p.y = as_float(next());
        p.z = as_float(next());
        p.pad = as_float(next());
        printf("obbrender %s\n", label(o));
        obb_render(o, &p);
        obbline(o);
        break;
    }
    case OP_OBBHIDE: {
        OBB *o;

        a = next();
        b = next();
        o = obb_at(a, b);
        printf("obbhide %s\n", label(o));
        obb_do_not_render(o);
        obbline(o);
        break;
    }
    case OP_OBBINIT: {
        OBB *o, *r;

        a = next();
        b = next();
        o = obb_at(a, b);
        printf("obbinit %s\n", label(o));
        r = obb_init(o);
        printf("  -> %s\n", label(r));
        obbline(o);
        break;
    }
    case OP_OBBDTOR: {
        OBB *o;

        a = next();
        b = next();
        o = obb_at(a, b);
        printf("obbdtor %s\n", label(o));
        obb_destroy(o);
        obbline(o);
        break;
    }
    case OP_SETOBBS:
        printf("setobbs\n");
        world_collision_prediction_set_obbs(&world, sm, so);
        for (i = 0; i < 4; i++)
            obbdump((uint32_t)i);
        break;
    case OP_SETDTS:
        a = next();
        b = next();
        printf("setdts DT%c DT%c\n", 'A' + (int)a, 'A' + (int)b);
        world_collision_prediction_set_drive_targets(&world, &dts[a], &dts[b]);
        break;
    case OP_RECPOT:
        a = next();
        printf("recpot DT%c\n", 'A' + (int)a);
        world_record_potential_drive_target(&world, &dts[a]);
        break;
    case OP_RECITER: {
        bVector2 m2, o2;

        a = next();
        b = next();
        c = next();
        m2.x = as_float(next());
        m2.y = as_float(next());
        o2.x = as_float(next());
        o2.y = as_float(next());
        printf("reciter %d %d %d\n", (int32_t)a, (int8_t)b, (int8_t)c);
        world_collision_prediction_record_iteration(&world, (int32_t)a,
                                                    (int8_t)b, (int8_t)c,
                                                    &m2, &o2);
        printf("  max %d\n", world.CollisionPredictionMaxLoopCounter);
        iterline((int)a);
        break;
    }
    case OP_PREDDUMP:
        printf("preddump\n");
        printf("  max %d\n", world.CollisionPredictionMaxLoopCounter);
        for (i = 0; i < WORLD_PREDICTION_ITERATIONS; i++)
            iterline(i);
        break;
    case OP_CTL:
        a = next();
        b = next();
        c = next();
        cars[a]->pCarController = (int32_t)b >= 0 ? &ctls[b] : NULL;
        cars[a]->pCarDriver =
            (int32_t)c >= 0 ? (CarDriver *)(void *)drv_obj[c] : NULL;
        printf("ctl CAR%u %d %d\n", a, (int32_t)b, (int32_t)c);
        break;
    case OP_SETTABLE:
        a = next();
        world.TotalNumCars = (int32_t)a;
        world.AICarPos = (int32_t)next();
        world.CopCarPos = (int32_t)next();
        world.TrafficCarPos = (int32_t)next();
        for (i = 0; i < (int)a; i++)
            world.CarTable[i] = cars[next()];
        printf("settable\n");
        table();
        break;
    case OP_DDSET:
        dd_ai = (int32_t)next();
        dd_cop = (int32_t)next();
        printf("ddset %d %d\n", dd_ai, dd_cop);
        break;
    case OP_DEBUGDISP:
        printf("debugdisplay\n");
        world_debug_display(&world);
        break;
    case OP_AITWEAK: {
        int32_t *g[5] = {
            &WhichCollisionPredictionIterationToRender,
            &WhichCarsRegisteredDriveTargetToRender,
            &RenderChosenPotentialDriveTarget, &RenderMyCarDriveTarget,
            &RenderOtherCarDriveTarget,
        };

        a = next();
        b = next();
        *g[a] = (int32_t)b;
        printf("aitweak %u %d\n", a, (int32_t)b);
        break;
    }
    case OP_AIDEBUG:
        printf("aidebug\n");
        world_update_ai_debug_rendering(&world);
        printf("  it %d\n", WhichCollisionPredictionIterationToRender);
        break;
    case OP_CUBES:
        a = next();
        b = next();
        printf("cubes %u %u\n", a, b);
        cubedump((int)a, (int)b);
        break;
    case OP_CUBE:
        a = next();
        fresh_cube((int)a);
        printf("cube WO%u\n", a);
        break;
    case OP_DSEED:
        bDefaultSeed = next();
        printf("dseed %08x\n", bDefaultSeed);
        break;
    case OP_CLOCK:
        WorldTimer = (int32_t)next();
        WorldTimeSeconds = as_float(next());
        WorldTime = (int32_t)next();
        WorldTimeFrames = (int32_t)next();
        WorldTimeElapsed = as_float(next());
        WorldTimeElapsedFrame = as_float(next());
        WorldLoopCounter = (int32_t)next();
        printf("clock\n");
        break;
    case OP_VOTSET:
        vot_set = (int32_t)next();
        printf("votset %d\n", vot_set);
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

static void install_vtable2(void)
{
    static VtEntry vt[CARCONTROLLER_VT_ENTRIES];

    vt[VT_SLOT(CARCONTROLLER_VT_DEBUG_DISPLAY)].delta = DELTA;
    vt[VT_SLOT(CARCONTROLLER_VT_DEBUG_DISPLAY)].fn = (VtFn)debug_display;
    vt_install(FAKE_VT2, vt, CARCONTROLLER_VT_ENTRIES);
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
    install_vtable2();
    for (i = 0; i < NCTL; i++)
        ctls[i]._vtable = FAKE_VT2;
    for (i = 0; i < NCAR; i++) {
        cars[i] = calloc(1, sizeof(struct Car));
        cars[i]->MyDriver = &dis[i];
    }
    for (i = 0; i < NB; i++)
        bodies[i].Dynamic.Body._vtable = FAKE_VT;
    world.CarList.next = world.CarList.prev = &world.CarList;
    world.AICarList.next = world.AICarList.prev = &world.AICarList;
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
    gServiceFernFlattenersFn = seam_ferns;
    gServiceTweakerDamageFn = seam_tweakdamage;
    gServiceTrackRouteEditorFn = seam_routeeditor;
    gRaceUpdateFn = seam_race;
    gRaceCoordinatorPostMessageFn = seam_post;
    gSmokeableBreakFn = seam_break;
    gDeleteFarAwaySmokeableCollisionBodiesFn = seam_farsmoke;

    gInitCarEffectsFn = seam_init_carfx;
    gInitClansFn = seam_init_clans;
    gInitSkidsFn = seam_init_skids;
    gInitParticlesFn = seam_init_particles;
    gInitMunitionsFn = seam_init_munitions;
    gInitFernFlattenersFn = seam_init_fernflat;
    gInitFernShakersFn = seam_init_fernshake;
    gSpawnSmokeablesFn = seam_spawn_smokeables;
    gInitTerrainEffectEmittersFn = seam_init_terrainfx;
    gInitCopsFn = seam_init_cops;
    gInitTrackGraphFn = seam_init_trackgraph;
    gCloseTerrainEffectEmittersFn = seam_close_terrainfx;
    gCleanupCopsFn = seam_cleanup_cops;
    gCleanupTrackGraphFn = seam_cleanup_trackgraph;
    gClearSmokeablesFn = seam_clear_smokeables;
    gCloseFernShakersFn = seam_close_fernshake;
    gCloseFernFlattenersFn = seam_close_fernflat;
    gCloseMunitionsFn = seam_close_munitions;
    gCloseParticlesFn = seam_close_particles;
    gCloseClansFn = seam_close_clans;
    gCloseSkidsFn = seam_close_skids;
    gCloseCarEffectsFn = seam_close_carfx;
    gTrafficTeleporterCtorFn = seam_tele_ctor;
    gTrafficTeleporterDestroyFn = seam_tele_dtor;
    gCarDestroyFn = seam_car_destroy;
    gWorldObjectNewFn = seam_wo_new;
    gWorldObjectDeleteFn = seam_wo_delete;

    while (fscanf(script, "%x", &op) == 1)
        step((uint32_t)op);
    fflush(stdout);
    return 0;
}
