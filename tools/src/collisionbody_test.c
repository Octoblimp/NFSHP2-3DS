// collisionbody_test -- the harness tools/collisionbody_check.py runs
// against the first two slices of CollisionBody.obj, 3DS Files/source/
// collisionbody.c, with track.c's tree, polyhedra.c's wafers and
// rigidbody.c beneath it.
//
// It reads the checker's op script from argv[1] -- little-endian words, the
// op and then its operands -- and prints what the model prints for the
// image. The ops, their operands and every line's format are the
// checker's, and so are the labels: H0..H15 are the bodies made in this
// file's memory, Tn, Wn, Kn and Pn the slots of the TrackPolygon-body, the
// witness, the car-body and the TrackPolygon pools, #n the nth block
// bMalloc handed out, na this file's NumberAllocator, poly0..poly3 the
// stand-in polyhedra and C1..C4 the stand-in Collisions. D0..D3 are the
// DynamicCollisionBodies, S0..S3 what their test tables' getters answer,
// dpoly0 and dpoly1 their polyhedra, RB0 and RB1 their RigidBodies, TC0 their
// TopologyCoordinate and PS0 their PhysicsSystem; testA and testB name the
// test tables, which the checker describes. CAR0..CAR2 are real Cars under
// the car bodies, PL0, M0 (a PhysicsCar), M1 (a MellowMover), AD0, DMG0,
// RC0 and COP0 what they and the globals point at, and PP0 and PP1 stand-in
// PipelinePolyhedrons; Car's four calls and the five seams are this file's
// stubs. E0..E3 are the contact bodies, car-sized, on testC, whose stubs
// answer from each one's scripted state; B0..B3 their boxes, Xn slot n of
// the Contact pool, and clist the contact list. The two Collision seams
// hand out C1..C4 in turn.
//
//     collisionbody_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "cartypeinfo.h"
#include "collisionbody.h"
#include "copmanager.h"
#include "mellowmover.h"
#include "p32.h"
#include "physicscar.h"
#include "physicssystem.h"
#include "player.h"
#include "polyhedra.h"
#include "race.h"
#include "realtime.h"
#include "rigidbody.h"
#include "topology.h"
#include "track.h"
#include "vclip.h"
#include "vtable.h"

enum {
    OP_TAG = 1, OP_STATIC_INIT, OP_STATIC_CLOSE, OP_INIT, OP_CLOSE,
    OP_TREE_INIT, OP_TREE_CLOSE, OP_TREE_LOAD, OP_FILL_H, OP_BASE_NEW,
    OP_STATIC_NEW, OP_TP_NEW, OP_VDEL, OP_DTOR, OP_SET_POLY, OP_SETBOX,
    OP_RAWBOX, OP_UPDW, OP_SETMAXW, OP_FLIP, OP_NAME, OP_FIND, OP_NEXTID,
    OP_GETCOLL, OP_ENABLE, OP_DISABLE, OP_BBOX, OP_BBOXB, OP_SETB,
    OP_NA_SET, OP_NA_ALLOC, OP_NA_ALLOCN, OP_NA_FREE, OP_NA_DESTROY,
    OP_NA_DUMP, OP_WIT_NEW, OP_WIT_DEL, OP_WIT_SETCOLL, OP_WIT_END,
    OP_EXPIRED, OP_EXISTS, OP_YAW, OP_ELIM, OP_VCALL, OP_VTDUMP, OP_DUMP,
    OP_STAT, OP_TPPOKE, OP_ACCESS,
    OP_DYN_NEW, OP_DYN_SETVT, OP_DYN_POKE, OP_DYN_PTRS, OP_DYN_SIDE, OP_DPOLY,
    OP_DYN_SETPOLY, OP_DYN_BUILD, OP_DYN_UPDATE, OP_DYN_BEGIN, OP_DYN_INTERP,
    OP_DYN_INTERPV, OP_DYN_BACKUP, OP_DYN_TESTVEL, OP_RB_SET, OP_RB_DUMP,
    OP_DYN_LOCAL, OP_DYN_WITNESSES, OP_DYN_CREATE_TP, OP_DYN_TPCHECK,
    OP_TP_ASSIGN, OP_TP_GEOM, OP_TC_SET, OP_SMOKE, OP_DYN_DTOR, OP_DYN_BBOX,
    OP_TP_FILL,
    OP_CAR_NEW, OP_CAR_DTOR, OP_CAR_FIELD, OP_CAR_SIDE, OP_CAR_COG, OP_GLOBAL,
    OP_PP, OP_CAR_MOVE, OP_CAR_APPLY, OP_CAR_DAMAGE, OP_CAR_ANIM, OP_CAR_TIMES,
    OP_CAR_STPM,
    OP_E_STATE, OP_E_QUEUE, OP_BOX, OP_BOX_SET, OP_TP_VERTS, OP_CT_INIT,
    OP_CT_CLOSE, OP_CT_TEST, OP_CT_RESOLVE, OP_CT_REMOVE, OP_CT_DUMP,
    OP_CT_NEW, OP_CT_TIME, OP_CT_CROWBAR, OP_CT_POINT, OP_CT_PLANAR,
    OP_CT_IMPULSE, OP_CT_CPV, OP_CT_DENOM, OP_CT_WAFER, OP_CT_SORT,
    OP_CT_GETCOLL, OP_CT_BEGIN, OP_CT_DEL, OP_CT_POKE, OP_CT_LINK,
    OP_WIT_CP,
    OP_COUNT
};

// CAR_FIELD's fields, and GLOBAL's globals.
enum { CF_DRIVER, CF_NAME, CF_PLAYER, CF_MODE, CF_MOVER, CF_ANIM, CF_DAMAGE,
       CF_BLINK, CF_POOF };
enum { G_BORING, G_WILLIAMS, G_RC, G_STATE, G_COP, G_TIMER, G_PORT,
       G_SEAMS, G_PRINT, G_LOOP, G_THRESH, G_BIAS, G_MINFACTOR, G_MINSPEED,
       G_SCRAPE };
// CT_POKE's fields: the backup time, CrowbarVector's lanes, LoopFound.
enum { XF_BT, XF_CV, XF_LF = XF_CV + 4 };

#define NH        16
#define NPOLY     4
#define NCOLL     4
#define NALLOC    256
#define REF_T     0x100u
#define REF_D     0x200u
#define REF_K     0x300u
#define NCARSLOT  14
#define NCAR      3
#define NPP       2
#define NPPVERT   8
#define NMOVE     8
#define ND        4
#define NDPOLY    2
#define NDVERT    8
#define NRB       2
#define NTPS      128
#define NSMOKE    16
#define RB_FIRST  16
#define RB_END    384
#define RB_WORDS  ((RB_END - RB_FIRST) / 4)
#define SIDE_WORDS 24
#define MAX_WALK  400
#define REF_E     0x400u
#define NE        4
#define NBOX      4
#define NEQ       8
#define E_VEC_WORDS 48                  // pos, vel, rot, cv, cw, inertia
#define E_WORDS   (E_VEC_WORDS + 6)

// The test tables' addresses, which no image table has.
#define TESTA_VT  0x00f10000u
#define TESTB_VT  0x00f10100u
#define PS_VT     0x00f10200u
#define TESTC_VT  0x00f10300u
#define REF_LIST  0x100u                // a contact: the nth on clist
#define REF_NEWEST 0x200u               // a contact: CT_NEW's last
#define CHUNK_MAX (16 * 1024 * 1024)

static uint32_t *words;
static size_t nwords, rd;

static uint32_t next(void)
{
    if (rd >= nwords) {
        fprintf(stderr, "script ends inside an op\n");
        exit(2);
    }
    return words[rd++];
}

static float fl(uint32_t b)
{
    float f;

    memcpy(&f, &b, 4);
    return f;
}

static uint32_t bits(float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    return b;
}

// ------------------------------------------------------------ the memory

static _Alignas(16) StaticCollisionBody hbody[NH];
static VCPolyhedron polys[NPOLY];
static VCVertex     pverts[NPOLY][2];
static _Alignas(16) uint8_t colls[NCOLL][16];
static NumberAllocator na;

typedef struct Side {
    bVector3 pos, vel;
    bMatrix4 rot;
} Side;

static _Alignas(16) DynamicCollisionBody dbody[ND];
static _Alignas(16) Side side[ND];
static VCPolyhedron dpolys[NDPOLY];
static VCVertex     dverts[NDPOLY][NDVERT];
static _Alignas(16) RigidBody rbs[NRB];
static TopologyCoordinate tc0;
static PhysicsSystem ps0;
static TrackPolygon *tps[NTPS];         // TP_ASSIGN's, in order
static int ntps;
static CollisionBody *smoke_from[NSMOKE], *smoke_to[NSMOKE];
static int nsmoke;

typedef char side_layout_check[sizeof(Side) == 4 * SIDE_WORDS ? 1 : -1];

// The car bodies' cars and what they point at. AD0, DMG0 and COP0 are only
// ever passed to the stubs, and RC0 is read for its first word.
static _Alignas(16) Car cars[NCAR];
static CarTypeInfo ctis[NCAR];
static Player pl0;
static PhysicsCar m0;
static MellowMover m1;
static _Alignas(16) uint8_t ad0[32], dmg0[32], cop0[32];
static int32_t rc0[36];
static PipelinePolyhedron pps[NPP];
static VCVertex ppverts[NPP][NPPVERT];
static int pp_linked[NPP];
static int32_t blink[NCAR], poof[NCAR];
static uint32_t move_q[NMOVE];
static int move_n, move_at;
static _Alignas(16) bVector3 cv[2];     // CAR_APPLY's two vectors

static const char *const car_names[] = { "DIABLO", "BUS", "NOSUCHCAR" };

// The contact bodies and what testC's stubs answer for each: the vectors
// as E_STATE writes them, then the four floats' bits, the two flags and
// ConsiderImpulse's queue, 1.0 once it runs out.
typedef struct EState {
    bVector3 pos, vel;
    bMatrix4 rot;
    bVector3 cv, cw;
    bMatrix4 inertia;
    uint32_t maxbackup, minv, bounce, friction;
    int32_t  moveable, blinking;
    uint32_t q[NEQ];
    int      nq, atq;
} EState;

typedef char estate_layout_check[
    offsetof(EState, maxbackup) == 4 * E_VEC_WORDS ? 1 : -1];

static _Alignas(16) CarCollisionBody ebody[NE];
static _Alignas(16) EState es[NE];
static _Alignas(16) RectPolyhedron boxes[NBOX];
static ContactNode clist;
static int ncoll_made;                  // the Collisions handed out
static _Alignas(16) bVector3 ctv[3];    // CT_CPV's and CT_DENOM's inputs
static _Alignas(16) bMatrix4 ctm;

// realtime.c's, which the harness does not link.
int32_t WorldTimer;
int32_t WorldLoopCounter;

static void *blocks[NALLOC];
static int nblocks;

static void *hook_malloc(int size, const char *name, int flags, int pool)
{
    void *p = malloc((size_t)size);
    int short_field = strcmp(name, "NumberAllocator") == 0
                      || strcmp(name, "CollisionBodyWitnessBitField") == 0;

    if (p == NULL || nblocks >= NALLOC) {
        fprintf(stderr, "out of blocks\n");
        exit(3);
    }
    // What the classes do not write shows as 0xa5 on both sides.
    memset(p, 0xa5, (size_t)size);
    if (short_field)
        printf("  malloc #%d %s %d fl %d mp %d\n", nblocks, name,
               size - COLLISIONBODY_SHORT_SLACK, flags, pool);
    else
        printf("  malloc #%d %s fl %d mp %d\n", nblocks, name, flags, pool);
    blocks[nblocks++] = p;
    return p;
}

static const char *label(const void *p);

static void hook_free(void *p)
{
    // Nothing is given back, so a stale pointer labels the same on both.
    printf("  free %s\n", label(p));
}

// One arena per pool, chosen by name and zeroed at every allocation, as
// the model hands each pool name its own fixed block.
#define ARENA(n, T) (BSLOTPOOL_HEADER_SIZE + (n) * sizeof(T) + 64)

static _Alignas(16) uint8_t arena_tpcb[ARENA(160, TrackPolygonCollisionBody)];
static _Alignas(16) uint8_t arena_car[ARENA(14, CarCollisionBody)];
static _Alignas(16) uint8_t arena_wit[ARENA(256, CollisionBodyWitness)];
static _Alignas(16) uint8_t arena_tp[ARENA(1024, TrackPolygon)];
static _Alignas(16) uint8_t arena_contact[ARENA(32, Contact)];

static const struct {
    const char *name;
    uint8_t *mem;
    size_t size;
} arenas[] = {
    { "TrackPolygonCollisionBodySlotPool", arena_tpcb, sizeof arena_tpcb },
    { "CarCollisionBodySlotPool", arena_car, sizeof arena_car },
    { "CollisionBodyWitnessSlotPool", arena_wit, sizeof arena_wit },
    { "TrackPolygonSlotPool", arena_tp, sizeof arena_tp },
    { "ContactSlotPool", arena_contact, sizeof arena_contact },
};
#define NARENA ((int)(sizeof arenas / sizeof arenas[0]))

static void *arena_alloc(size_t bytes, const char *name, int memoryPool)
{
    int i;

    for (i = 0; i < NARENA; i++) {
        if (strcmp(arenas[i].name, name) != 0)
            continue;
        if (bytes > arenas[i].size) {
            fprintf(stderr, "pool %s of %zu bytes does not fit\n", name,
                    bytes);
            exit(3);
        }
        printf("  pool alloc %s mp %d\n", name, memoryPool);
        memset(arenas[i].mem, 0, arenas[i].size);
        return arenas[i].mem;
    }
    fprintf(stderr, "no arena for pool %s\n", name);
    exit(3);
}

static void arena_release(void *block)
{
    int i;

    for (i = 0; i < NARENA; i++)
        if (block == arenas[i].mem) {
            printf("  pool free %s\n", arenas[i].name);
            return;
        }
    printf("  pool free ?\n");
}

static void printf_hook(const char *text)
{
    (void)text;
    printf("  printf\n");
}

static void coll_destroy(struct Collision *c, int32_t flags)
{
    printf("  ~collision %s %d\n", label(c), flags);
}

// ------------------------------------------------------------ the labels

// The slot `p` is in, and its offset there in *off, or -1.
static int in_pool(const BSlotPool *pool, const void *p, ptrdiff_t *off)
{
    const char *base;
    ptrdiff_t d;

    if (pool == NULL)
        return -1;
    base = (const char *)pool + BSLOTPOOL_HEADER_SIZE;
    d = (const char *)p - base;
    if (d < 0 || d >= (ptrdiff_t)pool->numSlots * pool->slotSize)
        return -1;
    *off = d % pool->slotSize;
    return (int)(d / pool->slotSize);
}

static const char *label(const void *p)
{
    static char buf[16][40];
    static int k;
    char *s = buf[k++ & 15];
    ptrdiff_t off;
    int i;

    if (p == NULL)
        return "null";
    if (p == &CollisionBodyList)
        return "blist";
    if (p == &CollisionBodyWitnessList)
        return "wlist";
    if (p == &ZeroVector)
        return "ZeroVector";
    if (p == &IdentityMatrix)
        return "IdentityMatrix";
    if (p == &ZeroMatrix)
        return "ZeroMatrix";
    if (p == &na)
        return "na";
    for (i = 0; i < NH; i++)
        if (p == &hbody[i])
            return snprintf(s, 40, "H%d", i), s;
    for (i = 0; i < NPOLY; i++)
        if (p == &polys[i])
            return snprintf(s, 40, "poly%d", i), s;
    for (i = 0; i < NCOLL; i++)
        if (p == colls[i])
            return snprintf(s, 40, "C%d", i + 1), s;
    for (i = 0; i < ND; i++) {
        if (p == &dbody[i])
            return snprintf(s, 40, "D%d", i), s;
        if (p == &side[i].pos)
            return snprintf(s, 40, "S%d.pos", i), s;
        if (p == &side[i].vel)
            return snprintf(s, 40, "S%d.vel", i), s;
        if (p == &side[i].rot)
            return snprintf(s, 40, "S%d.rot", i), s;
    }
    for (i = 0; i < NDPOLY; i++)
        if (p == &dpolys[i])
            return snprintf(s, 40, "dpoly%d", i), s;
    for (i = 0; i < NRB; i++) {
        if (p == &rbs[i])
            return snprintf(s, 40, "RB%d", i), s;
        if (p == &rbs[i].I_body_inv)
            return snprintf(s, 40, "RB%d.inv", i), s;
        if (p == &rbs[i].State.X)
            return snprintf(s, 40, "RB%d.x", i), s;
        if (p == &rbs[i].State.R)
            return snprintf(s, 40, "RB%d.r", i), s;
        if (p == &rbs[i].Velocity)
            return snprintf(s, 40, "RB%d.v", i), s;
    }
    if (p == &tc0)
        return "TC0";
    if (p == &ps0)
        return "PS0";
    for (i = 0; i < NCAR; i++) {
        if (p == &cars[i])
            return snprintf(s, 40, "CAR%d", i), s;
        if (p == &cars[i].TheTopologyCoordinate)
            return snprintf(s, 40, "CAR%d.tc", i), s;
        if (p == &cars[i].State.Position)
            return snprintf(s, 40, "CAR%d.pos", i), s;
        if (p == &cars[i].State.Velocity)
            return snprintf(s, 40, "CAR%d.vel", i), s;
        if (p == &cars[i].State.BodyMatrix)
            return snprintf(s, 40, "CAR%d.rot", i), s;
    }
    if (p == &pl0)
        return "PL0";
    if (p == &m0)
        return "M0";
    if (p == &m0.Vehicle)
        return "M0.sys";
    if (p == &m1)
        return "M1";
    if (p == &m1.Vehicle)
        return "M1.sys";
    if (p == ad0)
        return "AD0";
    if (p == dmg0)
        return "DMG0";
    if (p == rc0)
        return "RC0";
    if (p == cop0)
        return "COP0";
    for (i = 0; i < NPP; i++)
        if (p == &pps[i])
            return snprintf(s, 40, "PP%d", i), s;
    if (p == &clist)
        return "clist";
    for (i = 0; i < NE; i++)
        if (p == &ebody[i])
            return snprintf(s, 40, "E%d", i), s;
    for (i = 0; i < NBOX; i++)
        if (p == &boxes[i])
            return snprintf(s, 40, "B%d", i), s;
    if ((i = in_pool(ContactSlotPool, p, &off)) >= 0)
        return snprintf(s, 40, off ? "X%d+?" : "X%d", i), s;
    if ((i = in_pool(CarCollisionBodySlotPool, p, &off)) >= 0
        && off == (ptrdiff_t)offsetof(CarCollisionBody,
                                      ScaledInverseInertiaTensor))
        return snprintf(s, 40, "K%d.sit", i), s;
    if ((i = in_pool(TrackPolygonCollisionBodySlotPool, p, &off)) >= 0) {
        if (off == 0)
            snprintf(s, 40, "T%d", i);
        else if (off == (ptrdiff_t)offsetof(TrackPolygonCollisionBody,
                                             Wafer))
            snprintf(s, 40, "T%d.poly", i);
        else
            snprintf(s, 40, "T%d+?", i);
        return s;
    }
    if ((i = in_pool(CollisionBodyWitnessSlotPool, p, &off)) >= 0)
        return snprintf(s, 40, off ? "W%d+?" : "W%d", i), s;
    if ((i = in_pool(CarCollisionBodySlotPool, p, &off)) >= 0)
        return snprintf(s, 40, off ? "K%d+?" : "K%d", i), s;
    if ((i = in_pool(TrackPolygonSlotPool, p, &off)) >= 0)
        return snprintf(s, 40, off ? "P%d+?" : "P%d", i), s;
    for (i = 0; i < nblocks; i++)
        if (p == blocks[i])
            return snprintf(s, 40, "#%d", i), s;
    return "?";
}

static CollisionBody *body(uint32_t r)
{
    if (r < NH)
        return &hbody[r].Body;
    if (r >= REF_T && r < REF_T + 160 && TrackPolygonCollisionBodySlotPool)
        return (CollisionBody *)bGetSlot(TrackPolygonCollisionBodySlotPool,
                                         (int)(r - REF_T));
    if (r >= REF_D && r < REF_D + ND)
        return &dbody[r - REF_D].Body;
    if (r >= REF_K && r < REF_K + NCARSLOT && CarCollisionBodySlotPool)
        return (CollisionBody *)bGetSlot(CarCollisionBodySlotPool,
                                         (int)(r - REF_K));
    if (r >= REF_E && r < REF_E + NE)
        return &ebody[r - REF_E].Dynamic.Body;
    fprintf(stderr, "bad body %#x\n", r);
    exit(2);
}

static DynamicCollisionBody *dyn(uint32_t r)
{
    if (r >= REF_D && r < REF_D + ND)
        return &dbody[r - REF_D];
    if (r >= REF_K && r < REF_K + NCARSLOT && CarCollisionBodySlotPool)
        return (DynamicCollisionBody *)bGetSlot(CarCollisionBodySlotPool,
                                                (int)(r - REF_K));
    if (r >= REF_E && r < REF_E + NE)
        return &ebody[r - REF_E].Dynamic;
    fprintf(stderr, "bad dynamic body %#x\n", r);
    exit(2);
}

static const char *vtname(uint32_t vt)
{
    static char buf[4][12];
    static int k;
    char *s = buf[k++ & 3];

    if (vt == TESTA_VT)
        return "testA";
    if (vt == TESTB_VT)
        return "testB";
    if (vt == TESTC_VT)
        return "testC";
    snprintf(s, 12, "%08x", vt);
    return s;
}

static int is_dynamic_table(uint32_t vt)
{
    return vt == DYNAMICCOLLISIONBODY_VTABLE || vt == TESTA_VT
        || vt == TESTB_VT || vt == CARCOLLISIONBODY_VTABLE
        || vt == TESTC_VT;
}

static CollisionBodyWitness *witness(uint32_t s)
{
    return (CollisionBodyWitness *)bGetSlot(CollisionBodyWitnessSlotPool,
                                            (int)s);
}

// A witness's feature: the first vertex of its polyhedron, or a label.
static const char *feature(const VCFeature *f, const VCPolyhedron *p)
{
    if (f == NULL)
        return "null";
    if (p != NULL && p->pVertices != NULL
        && f == &p->pVertices[0].Feature)
        return "v0";
    return "?";
}

// ------------------------------------------------------------ the dumps

static void dump_pool(const char *name, const BSlotPool *p)
{
    if (p == NULL) {
        printf("  pool %s null\n", name);
        return;
    }
    printf("  pool %s flags %u alloc %d most %d slots %d total %d free %s\n",
           name, p->flags, p->numAllocatedSlots, p->mostNumAllocatedSlots,
           p->numSlots, p->totalNumSlots, label(p->freeSlots));
}

// " %08x" for each of `n` words at `p`.
static void print_words(const char *pre, const void *p, int n)
{
    uint32_t w;
    int i;

    printf("%s", pre);
    for (i = 0; i < n; i++) {
        memcpy(&w, (const char *)p + 4 * i, 4);
        printf(" %08x", w);
    }
}

static void dump_dynamic(DynamicCollisionBody *d)
{
    int i;

    printf("    dyn pm %d tc %s sys %s rb %s bt %08x\n", d->PhysicsMode,
           label(d->pTC), label(d->pSystem), label(d->pBody),
           bits(d->BackupTime));
    print_words("    brot", &d->BackupRotation, 16);
    printf("\n");
    print_words("    bpos", &d->BackupPosition, 4);
    print_words(" bvel", &d->BackupVelocity, 4);
    printf("\n");
    print_words("    cyl", &d->CylinderBaseHeight, 3);
    printf(" r %08x", bits(d->Radius));
    print_words(" lbb", &d->LocalBBMin, 4);
    print_words("", &d->LocalBBMax, 4);
    printf("\n");
    for (i = 0; i < ND; i++)
        if (d == &dbody[i]) {
            print_words("    side", &side[i], SIDE_WORDS);
            printf("\n");
        }
    for (i = 0; i < NE; i++)
        if (d == &ebody[i].Dynamic) {
            printf("    e col %08x pen %08x yaw %08x\n",
                   ebody[i].LastCollisionTime.PackedTime,
                   ebody[i].LastPenetrationTime.PackedTime,
                   ebody[i].LastYawControlCollisionTime.PackedTime);
            print_words("    epos", &es[i].pos, 8);
            print_words(" cv", &es[i].cv, 8);
            printf("\n");
        }
    if (d->Body._vtable == CARCOLLISIONBODY_VTABLE) {
        CarCollisionBody *c = (CarCollisionBody *)d;

        printf("    car %s col %08x pen %08x yaw %08x\n", label(c->pCar),
               c->LastCollisionTime.PackedTime,
               c->LastPenetrationTime.PackedTime,
               c->LastYawControlCollisionTime.PackedTime);
        print_words("    sit", &c->ScaledInverseInertiaTensor, 16);
        printf("\n");
        for (i = 0; i < nblocks; i++)
            if (blocks[i] == (void *)d->Body.pPoly)
                break;
        if (i < nblocks) {              // the box: its corners and faces
            RectPolyhedron *r = (RectPolyhedron *)d->Body.pPoly;

            for (i = 0; i < 8; i++)
                printf("    v%d %08x %08x %08x\n", i,
                       bits(r->VertexArray[i].CompressedPosition[0]),
                       bits(r->VertexArray[i].CompressedPosition[1]),
                       bits(r->VertexArray[i].CompressedPosition[2]));
            for (i = 0; i < 6; i++)
                printf("    f%d %08x %08x %08x %08x\n", i,
                       bits(r->FaceArray[i].Plane.CompressedNormal[0]),
                       bits(r->FaceArray[i].Plane.CompressedNormal[1]),
                       bits(r->FaceArray[i].Plane.CompressedNormal[2]),
                       bits(r->FaceArray[i].Plane.CompressedPlaneDistance));
        }
    }
}

static void dump_body(CollisionBody *b)
{
    int i;

    printf("  body %s vt %s type %d dyn %d id %d nw %d dis %d nc %d "
           "act %d bb %08x %08x %08x %08x poly %s caff %s\n",
           label(b), vtname(b->_vtable), b->Type, b->Dynamic, b->ID,
           b->NumWitnesses, b->CollisionsDisabled, b->NumCollisions,
           b->ActiveCollisionDetection, bits(b->BBoxMin.x),
           bits(b->BBoxMin.y), bits(b->BBoxMax.x), bits(b->BBoxMax.y),
           label(b->pPoly), label(b->pCaffeineObj));
    printf("    name");
    for (i = 0; i < 40; i++)
        printf("%s%02x", i % 8 ? "" : " ", (uint8_t)b->DebugName[i]);
    printf("\n");
    if (is_dynamic_table(b->_vtable)) {
        dump_dynamic((DynamicCollisionBody *)b);
        return;
    }
    if (b->_vtable == TRACKPOLYGONCOLLISIONBODY_VTABLE) {
        TrackPolygonCollisionBody *t = (TrackPolygonCollisionBody *)b;
        VCPolyhedron *p = &t->Wafer.Poly;
        int nv = p->NumVertices, nf = p->NumFaces;

        printf("    tp %s wafer num %d %d %d %d max %d %d %d %d dyn %d "
               "caff %s arr %s %s %s %s\n",
               label(t->pTP), p->NumVertices, p->NumEdges, p->NumFaces,
               p->NumPlanes, p->MaxVertices, p->MaxEdges, p->MaxFaces,
               p->MaxPlanes, p->DynamicallyAllocated, label(p->pCaffeineObj),
               (void *)p->pVertices == (void *)t->Wafer.VertexArray ? "va"
                                                                    : "?",
               (void *)p->pEdges == (void *)t->Wafer.EdgeArray ? "ea" : "?",
               (void *)p->pFaces == (void *)t->Wafer.FaceArray ? "fa" : "?",
               (void *)p->pPlanes == (void *)t->Wafer.PlaneArray ? "pa"
                                                                 : "?");
        if (nv < 0 || nv > 4)
            nv = 0;
        if (nf < 0 || nf > 2)
            nf = 0;
        for (i = 0; i < nv; i++)
            printf("    v%d %08x %08x %08x\n", i,
                   bits(t->Wafer.VertexArray[i].CompressedPosition[0]),
                   bits(t->Wafer.VertexArray[i].CompressedPosition[1]),
                   bits(t->Wafer.VertexArray[i].CompressedPosition[2]));
        for (i = 0; i < nf; i++)
            printf("    f%d %08x %08x %08x %08x\n", i,
                   bits(t->Wafer.FaceArray[i].Plane.CompressedNormal[0]),
                   bits(t->Wafer.FaceArray[i].Plane.CompressedNormal[1]),
                   bits(t->Wafer.FaceArray[i].Plane.CompressedNormal[2]),
                   bits(t->Wafer.FaceArray[i].Plane.CompressedPlaneDistance));
    }
}

static void dump_witness(CollisionBodyWitness *w)
{
    VCWitness *v = &w->Witness;

    printf("  wit %s b1 %s b2 %s coll %s ss %d f1 %s f2 %s p1 %s p2 %s "
           "cp %08x %08x %08x %08x %08x %08x dist %08x caff %s %s\n",
           label(w), label(w->pBody1), label(w->pBody2), label(w->pCollision),
           v->SwitchState, feature(v->F1, v->P1), feature(v->F2, v->P2),
           label(v->P1), label(v->P2), bits(v->CP1.x), bits(v->CP1.y),
           bits(v->CP1.z), bits(v->CP2.x), bits(v->CP2.y), bits(v->CP2.z),
           bits(v->Distance), label(v->pCaffeineObj1),
           label(v->pCaffeineObj2));
}

static void dump_bits(const char *pre, const uint8_t *f, int bytes)
{
    int i;

    printf("%s", pre);
    for (i = 0; i < bytes; i++)
        printf(" %02x", f[i]);
    printf("\n");
}

static void dump(void)
{
    const float *m;
    int i, n;

    printf("dump\n");
    printf("  zv %08x %08x %08x %08x\n", bits(ZeroVector.x),
           bits(ZeroVector.y), bits(ZeroVector.z), bits(ZeroVector.pad));
    m = (const float *)&IdentityMatrix;
    printf("  im");
    for (i = 0; i < 16; i++)
        printf(" %08x", bits(m[i]));
    printf("\n");
    m = (const float *)&ZeroMatrix;
    printf("  zm");
    for (i = 0; i < 16; i++)
        printf(" %08x", bits(m[i]));
    printf("\n");
    {
        const int32_t *s = (const int32_t *)&TheCollisionStats;

        printf("  stats");
        for (i = 0; i < 18; i++)
            printf(" %d", s[i]);
        printf("\n");
    }
    printf("  maxw %08x\n", bits(MaxCollisionBodyWidthX));
    printf("  heads %s %s %s %s\n", label(CollisionBodyList.next),
           label(CollisionBodyList.prev),
           label(CollisionBodyWitnessList.next),
           label(CollisionBodyWitnessList.prev));
    printf("  ptrs table %s alloc %s wbits %s\n", label(pCollisionBodyTable),
           label(pCollisionBodyNumberAllocator),
           label(pWitnessExistanceBitField));
    if (pCollisionBodyTable != NULL) {
        printf("  table");
        for (i = 0; i < COLLISIONBODY_MAX_BODIES; i++)
            if (pCollisionBodyTable[i] != NULL)
                printf(" %d:%s", i, label(pCollisionBodyTable[i]));
        printf("\n");
    }
    if (pCollisionBodyNumberAllocator != NULL) {
        NumberAllocator *a = pCollisionBodyNumberAllocator;

        printf("  alloc max %d lowest %d field %s\n", a->MaxNumbers,
               a->LowestFreeNumber, label(a->pAllocatedBitField));
        if (a->pAllocatedBitField != NULL && a->MaxNumbers > 0)
            dump_bits("   ", a->pAllocatedBitField, (a->MaxNumbers >> 3) + 1);
    }
    if (pWitnessExistanceBitField != NULL) {
        printf("  wbits");
        for (i = 0; i < (COLLISIONBODY_BITFIELD_BYTES + 1) * 8; i++)
            if (pWitnessExistanceBitField[i >> 3] & (1 << (i & 7)))
                printf(" %d,%d", i / COLLISIONBODY_MAX_BODIES,
                       i % COLLISIONBODY_MAX_BODIES);
        printf("\n");
    }
    dump_pool("tpcb", TrackPolygonCollisionBodySlotPool);
    dump_pool("car", CarCollisionBodySlotPool);
    dump_pool("wit", CollisionBodyWitnessSlotPool);
    dump_pool("tp", TrackPolygonSlotPool);

    if (CollisionBodyList.next != NULL) {
        CollisionBody *b;

        printf("  list");
        n = 0;
        for (b = CollisionBodyList.next;
             b != (CollisionBody *)(void *)&CollisionBodyList && n < MAX_WALK;
             b = b->Link.next, n++)
            printf(" %s", label(b));
        printf(" |");
        n = 0;
        for (b = CollisionBodyList.prev;
             b != (CollisionBody *)(void *)&CollisionBodyList && n < MAX_WALK;
             b = b->Link.prev, n++)
            printf(" %s", label(b));
        printf("\n");
        n = 0;
        for (b = CollisionBodyList.next;
             b != (CollisionBody *)(void *)&CollisionBodyList && n < MAX_WALK;
             b = b->Link.next, n++)
            dump_body(b);
    }
    if (CollisionBodyWitnessList.next != NULL) {
        CollisionBodyWitness *w;
        CollisionBodyWitness *end =
            (CollisionBodyWitness *)(void *)&CollisionBodyWitnessList;

        printf("  wlist");
        n = 0;
        for (w = CollisionBodyWitnessList.next; w != end && n < MAX_WALK;
             w = w->Link.next, n++)
            printf(" %s", label(w));
        printf(" |");
        n = 0;
        for (w = CollisionBodyWitnessList.prev; w != end && n < MAX_WALK;
             w = w->Link.prev, n++)
            printf(" %s", label(w));
        printf("\n");
        n = 0;
        for (w = CollisionBodyWitnessList.next; w != end && n < MAX_WALK;
             w = w->Link.next, n++)
            dump_witness(w);
    }
    if (TrackPolygonSlotPool != NULL) {
        TrackListNode *head = &TheTopologyTree.TrackPolygonList;
        TrackListNode *nd;

        n = 0;
        for (nd = p32_ptr(head->pNext); nd != head && n < MAX_WALK;
             nd = p32_ptr(nd->pNext), n++) {
            TrackPolygon *tp = (TrackPolygon *)nd;

            printf("  tp %s ref %d fl %d ty %d cb %s\n", label(tp),
                   tp->ReferenceCount, tp->Flags, tp->TheTerrainType,
                   label(tp->pCollisionBody));
        }
    }
    for (i = 0; i < NPP && !pp_linked[i]; i++)
        ;
    if (i < NPP) {
        VCPolyhedron *head = (VCPolyhedron *)(void *)&PipelinePolyhedronList;
        VCPolyhedron *p;

        printf("  pplist");
        n = 0;
        for (p = PipelinePolyhedronList.next; p != head && n < MAX_WALK;
             p = p->Link.next, n++)
            printf(" %s", label(p));
        printf(" |");
        n = 0;
        for (p = PipelinePolyhedronList.prev; p != head && n < MAX_WALK;
             p = p->Link.prev, n++)
            printf(" %s", label(p));
        printf("\n");
        for (i = 0; i < NPP; i++) {
            PipelinePolyhedron *pp = &pps[i];
            int j, nv = pp->Poly.NumVertices;

            if (!pp_linked[i])
                continue;
            printf("  pp PP%d hash %08x fixed %d n %d va %s\n", i,
                   pp->NameHash, pp->CenterOfGravityFixed, nv,
                   pp->Poly.pVertices == ppverts[i] ? "ok" : "?");
            for (j = 0; j < nv && j < NPPVERT; j++)
                printf("    v%d %08x %08x %08x\n", j,
                       bits(ppverts[i][j].CompressedPosition[0]),
                       bits(ppverts[i][j].CompressedPosition[1]),
                       bits(ppverts[i][j].CompressedPosition[2]));
        }
    }
}

// The five tables, entry by entry, each function by its image name.
static const struct {
    VtFn fn;
    const char *name;
} fnames[] = {
#define N(f, s) { (VtFn)(f), s }
    N(collisionbody_destroy, "_$_13CollisionBody"),
    N(collisionbody_is_blinking, "IsBlinking__13CollisionBody"),
    N(collisionbody_do_snapshot,
      "DoSnapshot__13CollisionBodyP14ReplaySnapshot"),
    N(staticcollisionbody_destroy, "_$_19StaticCollisionBody"),
    N(staticcollisionbody_do_snapshot,
      "DoSnapshot__19StaticCollisionBodyP14ReplaySnapshot"),
    N(staticcollisionbody_get_velocity, "GetVelocity__19StaticCollisionBody"),
    N(staticcollisionbody_get_rotation, "GetRotation__19StaticCollisionBody"),
    N(staticcollisionbody_set_position,
      "SetPosition__19StaticCollisionBodyP8bVector3"),
    N(staticcollisionbody_get_max_backup_time,
      "GetMaxBackupTime__19StaticCollisionBody"),
    N(staticcollisionbody_move, "Move__19StaticCollisionBodyf"),
    N(staticcollisionbody_backup, "Backup__19StaticCollisionBodyf"),
    N(staticcollisionbody_interpolate,
      "Interpolate__19StaticCollisionBodyP8bVector3P8bMatrix4f"),
    N(staticcollisionbody_recompute_auxilliaries,
      "RecomputeAuxilliaries__19StaticCollisionBody"),
    N(staticcollisionbody_get_current_velocities,
      "GetCurrentVelocities__19StaticCollisionBodyR8bVector3T1"),
    N(staticcollisionbody_get_test_impulse_velocities,
      "GetTestImpulseVelocities__19StaticCollisionBodyR8bVector3T1T1T1"),
    N(staticcollisionbody_set_to_physics_mode,
      "SetToPhysicsMode__19StaticCollisionBodyP13CollisionBody"),
    N(staticcollisionbody_consider_impulse,
      "ConsiderImpulse__19StaticCollisionBodyP8bVector3T1"),
    N(staticcollisionbody_apply_impulse,
      "ApplyImpulse__19StaticCollisionBodyP8bVector3T1"),
    N(staticcollisionbody_are_collisions_enabled,
      "AreCollisionsEnabled__19StaticCollisionBody"),
    N(staticcollisionbody_get_mass_inverse,
      "GetMassInverse__19StaticCollisionBody"),
    N(staticcollisionbody_get_inertia_tensor_inverse,
      "GetInertiaTensorInverse__19StaticCollisionBody"),
    N(staticcollisionbody_is_moveable, "IsMoveable__19StaticCollisionBody"),
    N(staticcollisionbody_change_in_energy,
      "ChangeInEnergy__19StaticCollisionBodyP8bVector3T1"),
    N(staticcollisionbody_get_bounciness,
      "GetBounciness__19StaticCollisionBody"),
    N(staticcollisionbody_get_friction, "GetFriction__19StaticCollisionBody"),
    N(trackpolygoncollisionbody_destroy, "_$_25TrackPolygonCollisionBody"),
    N(trackpolygoncollisionbody_do_snapshot,
      "DoSnapshot__25TrackPolygonCollisionBodyP14ReplaySnapshot"),
    N(trackpolygoncollisionbody_get_position,
      "GetPosition__25TrackPolygonCollisionBody"),
    N(trackpolygoncollisionbody_get_terrain_type,
      "GetTerrainType__25TrackPolygonCollisionBody"),
    N(dynamiccollisionbody_destroy, "_$_20DynamicCollisionBody"),
    N(dynamiccollisionbody_set_position,
      "SetPosition__20DynamicCollisionBodyP8bVector3"),
    N(dynamiccollisionbody_get_max_backup_time,
      "GetMaxBackupTime__20DynamicCollisionBody"),
    N(dynamiccollisionbody_backup, "Backup__20DynamicCollisionBodyf"),
    N(dynamiccollisionbody_interpolate,
      "Interpolate__20DynamicCollisionBodyP8bVector3P8bMatrix4f"),
    N(dynamiccollisionbody_recompute_auxilliaries,
      "RecomputeAuxilliaries__20DynamicCollisionBody"),
    N(dynamiccollisionbody_get_current_velocities,
      "GetCurrentVelocities__20DynamicCollisionBodyR8bVector3T1"),
    N(dynamiccollisionbody_get_test_impulse_velocities,
      "GetTestImpulseVelocities__20DynamicCollisionBodyR8bVector3T1T1T1"),
    N(dynamiccollisionbody_set_to_physics_mode,
      "SetToPhysicsMode__20DynamicCollisionBodyP13CollisionBody"),
    N(dynamiccollisionbody_apply_impulse,
      "ApplyImpulse__20DynamicCollisionBodyP8bVector3T1"),
    N(dynamiccollisionbody_get_mass_inverse,
      "GetMassInverse__20DynamicCollisionBody"),
    N(dynamiccollisionbody_get_inertia_tensor_inverse,
      "GetInertiaTensorInverse__20DynamicCollisionBody"),
    N(dynamiccollisionbody_do_snapshot,
      "DoSnapshot__20DynamicCollisionBodyP14ReplaySnapshot"),
    N(dynamiccollisionbody_change_in_energy,
      "ChangeInEnergy__20DynamicCollisionBodyP8bVector3T1"),
    N(carcollisionbody_destroy, "_$_16CarCollisionBody"),
    N(carcollisionbody_do_snapshot,
      "DoSnapshot__16CarCollisionBodyP14ReplaySnapshot"),
    N(carcollisionbody_get_position, "GetPosition__16CarCollisionBody"),
    N(carcollisionbody_get_velocity, "GetVelocity__16CarCollisionBody"),
    N(carcollisionbody_get_rotation, "GetRotation__16CarCollisionBody"),
    N(carcollisionbody_move, "Move__16CarCollisionBodyf"),
    N(carcollisionbody_set_to_physics_mode,
      "SetToPhysicsMode__16CarCollisionBodyP13CollisionBody"),
    N(carcollisionbody_consider_impulse,
      "ConsiderImpulse__16CarCollisionBodyP8bVector3T1"),
    N(carcollisionbody_apply_impulse,
      "ApplyImpulse__16CarCollisionBodyP8bVector3T1"),
    N(carcollisionbody_are_collisions_enabled,
      "AreCollisionsEnabled__16CarCollisionBody"),
    N(carcollisionbody_get_terrain_type, "GetTerrainType__16CarCollisionBody"),
    N(carcollisionbody_get_mass_inverse, "GetMassInverse__16CarCollisionBody"),
    N(carcollisionbody_get_inertia_tensor_inverse,
      "GetInertiaTensorInverse__16CarCollisionBody"),
    N(carcollisionbody_is_moveable, "IsMoveable__16CarCollisionBody"),
    N(carcollisionbody_is_blinking, "IsBlinking__16CarCollisionBody"),
    N(carcollisionbody_get_bounciness, "GetBounciness__16CarCollisionBody"),
    N(carcollisionbody_get_friction, "GetFriction__16CarCollisionBody"),
#undef N
};

static const char *fname(VtFn fn, int slot)
{
    size_t i;

    if (fn == NULL)
        return slot == 0 ? "0" : "__pure_virtual";
    for (i = 0; i < sizeof fnames / sizeof fnames[0]; i++)
        if (fnames[i].fn == fn)
            return fnames[i].name;
    return "?";
}

static void vt_dump(void)
{
    static const uint32_t vts[] = { COLLISIONBODY_VTABLE,
                                    STATICCOLLISIONBODY_VTABLE,
                                    TRACKPOLYGONCOLLISIONBODY_VTABLE,
                                    DYNAMICCOLLISIONBODY_VTABLE,
                                    CARCOLLISIONBODY_VTABLE };
    size_t t;
    int i, n;

    for (t = 0; t < sizeof vts / sizeof vts[0]; t++) {
        const VtEntry *e = vt_table(vts[t], &n);

        printf("vt %08x %d\n", vts[t], n);
        for (i = 0; i < n; i++)
            printf("  %d %d %d %s\n", 8 * i, e[i].delta, e[i].index,
                   fname(e[i].fn, 8 * i));
    }
}

// ------------------------------------------------------------ the calls

typedef void    *(*FnP)(void *);
typedef void     (*FnV)(void *);
typedef void     (*FnVD)(void *, int32_t);
typedef void     (*FnVP)(void *, bVector3 *);
typedef float    (*FnF)(void *);
typedef void     (*FnVF)(void *, float);
typedef void     (*FnInterp)(void *, bVector3 *, bMatrix4 *, float);
typedef void     (*FnV2)(void *, bVector3 *, bVector3 *);
typedef void     (*FnV4)(void *, bVector3 *, bVector3 *, bVector3 *,
                         bVector3 *);
typedef void     (*FnVB)(void *, CollisionBody *);
typedef float    (*FnF2)(void *, bVector3 *, bVector3 *);
typedef int32_t  (*FnI)(void *);

static _Alignas(16) bVector3 outv[4];
static _Alignas(16) bMatrix4 outm;
static _Alignas(16) bVector3 inv[2] = { { 1.0f, 2.0f, 3.0f, 4.0f },
                                        { -5.0f, 6.0f, -7.0f, 8.0f } };

static void print_outm(void);

static void print_vec(int k, const bVector3 *v)
{
    printf("  out%d %08x %08x %08x %08x\n", k, bits(v->x), bits(v->y),
           bits(v->z), bits(v->pad));
}

// The line is printed after the call, whose stubs may print their own.
static void vcall(CollisionBody *b, int slot)
{
    const VtEntry *e = vt_slot(b->_vtable, slot);
    void *self = vt_this(b, e);
    const char *who = label(b);
    char res[40] = "ok";
    int i, outs = 0, show_m = 0;

    memset(outv, 0x5a, sizeof outv);
    memset(&outm, 0x5a, sizeof outm);
    switch (slot) {
    case COLLISIONBODY_VT_GET_POSITION:
    case COLLISIONBODY_VT_GET_VELOCITY:
    case COLLISIONBODY_VT_GET_ROTATION:
    case COLLISIONBODY_VT_GET_INERTIA_TENSOR_INVERSE:
        snprintf(res, sizeof res, "%s", label(((FnP)e->fn)(self)));
        break;
    case COLLISIONBODY_VT_SET_POSITION:
        ((FnVP)e->fn)(self, &inv[0]);
        break;
    case COLLISIONBODY_VT_GET_MAX_BACKUP_TIME:
    case COLLISIONBODY_VT_GET_MASS_INVERSE:
    case COLLISIONBODY_VT_GET_BOUNCINESS:
    case COLLISIONBODY_VT_GET_FRICTION:
        snprintf(res, sizeof res, "%08x", bits(((FnF)e->fn)(self)));
        break;
    case COLLISIONBODY_VT_MOVE:
    case COLLISIONBODY_VT_BACKUP:
        ((FnVF)e->fn)(self, 0.25f);
        break;
    case COLLISIONBODY_VT_INTERPOLATE:
        ((FnInterp)e->fn)(self, &outv[0], &outm, 0.5f);
        outs = 1;
        show_m = 1;
        break;
    case COLLISIONBODY_VT_RECOMPUTE_AUXILLIARIES:
        ((FnV)e->fn)(self);
        break;
    case COLLISIONBODY_VT_GET_CURRENT_VELOCITIES:
        ((FnV2)e->fn)(self, &outv[0], &outv[1]);
        outs = 2;
        break;
    case COLLISIONBODY_VT_GET_TEST_IMPULSE_VELOCITIES:
        ((FnV4)e->fn)(self, &outv[0], &outv[1], &outv[2], &outv[3]);
        outs = 4;
        break;
    case COLLISIONBODY_VT_SET_TO_PHYSICS_MODE:
        ((FnVB)e->fn)(self, &hbody[0].Body);
        break;
    case COLLISIONBODY_VT_CONSIDER_IMPULSE:
    case COLLISIONBODY_VT_CHANGE_IN_ENERGY:
        snprintf(res, sizeof res, "%08x",
                 bits(((FnF2)e->fn)(self, &inv[0], &inv[1])));
        break;
    case COLLISIONBODY_VT_APPLY_IMPULSE:
        ((FnV2)e->fn)(self, &inv[0], &inv[1]);
        break;
    case COLLISIONBODY_VT_ARE_COLLISIONS_ENABLED:
    case COLLISIONBODY_VT_GET_TERRAIN_TYPE:
    case COLLISIONBODY_VT_IS_MOVEABLE:
    case COLLISIONBODY_VT_IS_BLINKING:
        snprintf(res, sizeof res, "%d", ((FnI)e->fn)(self));
        break;
    default:
        fprintf(stderr, "vcall of slot %d\n", slot);
        exit(2);
    }
    printf("vcall %s %d -> %s\n", who, slot, res);
    for (i = 0; i < outs; i++)
        print_vec(i, &outv[i]);
    if (show_m)
        print_outm();
}

// ------------------------------------------------------------ the stubs
//
// The test tables' entries carry a `this` delta of 8, and the
// PhysicsSystem's one of 4, which the callers add and the stubs take off.

static int dyn_index(void *self)
{
    char *b = (char *)self - 8;
    int k;

    for (k = 0; k < ND; k++)
        if (b == (char *)&dbody[k])
            return k;
    fprintf(stderr, "a test table's stub called on no dynamic body\n");
    exit(2);
}

static bVector3 *stub_getpos(void *self)
{
    int k = dyn_index(self);

    printf("  getpos D%d\n", k);
    return &side[k].pos;
}

static bVector3 *stub_getvel(void *self)
{
    int k = dyn_index(self);

    printf("  getvel D%d\n", k);
    return &side[k].vel;
}

static bMatrix4 *stub_getrot(void *self)
{
    int k = dyn_index(self);

    printf("  getrot D%d\n", k);
    return &side[k].rot;
}

static int32_t stub_enabled(void *self)
{
    CollisionBody *b = (CollisionBody *)(void *)((char *)self - 8);

    printf("  enabled %s\n", label(b));
    return b->CollisionsDisabled == 0;
}

// The position (t, -t, 3, 4); the rotation's rows count up from 1 with t
// down the diagonal and -t last.
static void stub_interp(void *self, bVector3 *pos, bMatrix4 *rot, float t)
{
    int k = dyn_index(self);
    uint32_t tb = bits(t), nt = tb ^ 0x80000000u;
    uint32_t v[20];
    int i, n = 1;

    printf("  interp D%d t %08x\n", k, tb);
    v[0] = tb;
    v[1] = nt;
    v[2] = bits(3.0f);
    v[3] = bits(4.0f);
    for (i = 0; i < 16; i++)
        v[4 + i] = i % 5 == 0 ? tb : bits((float)n++);
    v[19] = nt;
    memcpy(pos, v, 16);
    memcpy(rot, v + 4, 64);
}

static void stub_aux(void *self)
{
    printf("  aux %s\n", label((char *)self - 4));
}

static CollisionBody *stub_smoke(CollisionBody *b)
{
    CollisionBody *to = b;
    int i;

    for (i = 0; i < nsmoke; i++)
        if (smoke_from[i] == b)
            to = smoke_to[i];
    printf("  smokeable %s -> %s\n", label(b), label(to));
    return to;
}

// Car's four calls, which car.c and carmove.c make and the harness does not
// link: Move answers from CAR_MOVE's queue, then with the step it was given.
static int car_index(const Car *c)
{
    int k;

    for (k = 0; k < NCAR; k++)
        if (c == &cars[k])
            return k;
    fprintf(stderr, "a Car call on no car\n");
    exit(2);
}

float car_move(Car *c, float dt)
{
    int k = car_index(c);
    uint32_t r = move_at < move_n ? move_q[move_at++] : bits(dt);

    printf("  car-move CAR%d t %08x -> %08x\n", k, bits(dt), r);
    return fl(r);
}

int32_t car_is_blinking(Car *c)
{
    int k = car_index(c);

    printf("  car-blinking CAR%d -> %d\n", k, blink[k]);
    return blink[k];
}

int32_t car_is_poofed(Car *c)
{
    int k = car_index(c);

    printf("  car-poofed CAR%d -> %d\n", k, poof[k]);
    return poof[k];
}

void car_set_to_physics_mode(Car *c, Car *other)
{
    printf("  car-stpm %s them %s\n", label(c), label(other));
}

// The five seams.
static void stub_add_damage(struct CarDamage *d, const bVector3 *at,
                            float amount)
{
    printf("  add-damage %s at", label(d));
    print_words("", at, 4);
    printf(" amount %08x\n", bits(amount));
}

static void stub_rumble(int32_t port, float amount)
{
    printf("  rumble port %d amount %08x\n", port, bits(amount));
}

static void stub_monitor(struct tCopManager *m, struct CarCollisionBody *b,
                         float amount)
{
    printf("  monitor-impact %s %s amount %08x\n", label(m), label(b->pCar),
           bits(amount));
}

static void stub_begin(struct AnimatedDriver *d, int32_t type,
                       int32_t priority)
{
    printf("  begin-collision %s type %d prio %d\n", label(d), type,
           priority);
}

static void stub_force(struct Car *c, bVector3 *dir, float amount)
{
    printf("  force-impact %s dir", label(c));
    print_words("", dir, 4);
    printf(" amount %08x\n", bits(amount));
}

// testC's stubs, on the contact bodies.
static int e_index(void *self)
{
    char *b = (char *)self - 8;
    int k;

    for (k = 0; k < NE; k++)
        if (b == (char *)&ebody[k])
            return k;
    fprintf(stderr, "a testC stub called on no contact body\n");
    exit(2);
}

static bVector3 *e_getpos(void *self)
{
    int k = e_index(self);

    printf("  e-getpos E%d\n", k);
    return &es[k].pos;
}

static bVector3 *e_getvel(void *self)
{
    int k = e_index(self);

    printf("  e-getvel E%d\n", k);
    return &es[k].vel;
}

static bMatrix4 *e_getrot(void *self)
{
    int k = e_index(self);

    printf("  e-getrot E%d\n", k);
    return &es[k].rot;
}

static void e_setpos(void *self, bVector3 *p)
{
    int k = e_index(self);

    printf("  e-setpos E%d", k);
    print_words("", p, 4);
    printf("\n");
    es[k].pos = *p;
}

static float e_maxbackup(void *self)
{
    int k = e_index(self);

    printf("  e-maxbackup E%d -> %08x\n", k, es[k].maxbackup);
    return fl(es[k].maxbackup);
}

static void e_move(void *self, float t)
{
    printf("  e-move E%d %08x\n", e_index(self), bits(t));
}

static void e_backup(void *self, float t)
{
    printf("  e-backup E%d %08x\n", e_index(self), bits(t));
}

// Where the body was t ago: the position less t of the velocity, lane by
// lane, and the rotation as it is.
static void e_interp(void *self, bVector3 *pos, bMatrix4 *rot, float t)
{
    int k = e_index(self);
    EState *s = &es[k];
    volatile float x;

    printf("  e-interp E%d t %08x\n", k, bits(t));
    x = t * s->vel.x;
    pos->x = s->pos.x - x;
    x = t * s->vel.y;
    pos->y = s->pos.y - x;
    x = t * s->vel.z;
    pos->z = s->pos.z - x;
    x = t * s->vel.pad;
    pos->pad = s->pos.pad - x;
    *rot = s->rot;
}

static void e_aux(void *self)
{
    printf("  e-aux E%d\n", e_index(self));
}

static void e_curvel(void *self, bVector3 *v, bVector3 *w)
{
    int k = e_index(self);

    printf("  e-curvel E%d\n", k);
    *v = es[k].cv;
    *w = es[k].cw;
}

static void e_physmode(void *self, CollisionBody *other)
{
    printf("  e-physmode E%d them %s\n", e_index(self), label(other));
}

static float e_consider(void *self, bVector3 *j, bVector3 *at)
{
    int k = e_index(self);
    EState *s = &es[k];
    uint32_t r = s->atq < s->nq ? s->q[s->atq++] : bits(1.0f);

    printf("  e-consider E%d j", k);
    print_words("", j, 4);
    print_words(" at", at, 4);
    printf(" -> %08x\n", r);
    return fl(r);
}

// The velocity takes the mass inverse of the impulse, lane by lane.
static void e_apply(void *self, bVector3 *j, bVector3 *at)
{
    int k = e_index(self);
    EState *s = &es[k];
    float m = fl(s->minv);
    volatile float x;

    printf("  e-apply E%d j", k);
    print_words("", j, 4);
    print_words(" at", at, 4);
    printf("\n");
    x = m * j->x;
    s->cv.x = s->cv.x + x;
    x = m * j->y;
    s->cv.y = s->cv.y + x;
    x = m * j->z;
    s->cv.z = s->cv.z + x;
    x = m * j->pad;
    s->cv.pad = s->cv.pad + x;
}

static float e_massinv(void *self)
{
    int k = e_index(self);

    printf("  e-massinv E%d -> %08x\n", k, es[k].minv);
    return fl(es[k].minv);
}

static bMatrix4 *e_inertia(void *self)
{
    int k = e_index(self);

    printf("  e-inertia E%d\n", k);
    return &es[k].inertia;
}

static int32_t e_moveable(void *self)
{
    int k = e_index(self);

    printf("  e-moveable E%d -> %d\n", k, es[k].moveable);
    return es[k].moveable;
}

static int32_t e_blinking(void *self)
{
    int k = e_index(self);

    printf("  e-blinking E%d -> %d\n", k, es[k].blinking);
    return es[k].blinking;
}

static int32_t e_enabled(void *self)
{
    int k = e_index(self);
    int32_t r = ebody[k].Dynamic.Body.CollisionsDisabled == 0;

    printf("  e-enabled E%d -> %d\n", k, r);
    return r;
}

static float e_bounce(void *self)
{
    int k = e_index(self);

    printf("  e-bounce E%d -> %08x\n", k, es[k].bounce);
    return fl(es[k].bounce);
}

static float e_friction(void *self)
{
    int k = e_index(self);

    printf("  e-friction E%d -> %08x\n", k, es[k].friction);
    return fl(es[k].friction);
}

// Collision.obj's two, which contact.c reaches through its seams.
static struct Collision *coll_new(CollisionBodyWitness *w, bVector3 *pt)
{
    struct Collision *c = (struct Collision *)(void *)
                          colls[ncoll_made++ % NCOLL];

    printf("  collision-new %s at", label(w));
    print_words("", pt, 4);
    printf(" -> %s\n", label(c));
    return c;
}

static void coll_add_impulse(struct Collision *c, bVector3 *at,
                             bVector3 *impulse, float scrape)
{
    printf("  collision-impulse %s at", label(c));
    print_words("", at, 4);
    print_words(" j", impulse, 4);
    printf(" scrape %08x\n", bits(scrape));
}

static VtEntry vt_testa[COLLISIONBODY_VT_ENTRIES];
static VtEntry vt_testb[COLLISIONBODY_VT_ENTRIES];
static VtEntry vt_testc[COLLISIONBODY_VT_ENTRIES];
static VtEntry vt_ps[3];

// testA is the class's table with the getters and AreCollisionsEnabled
// stubbed, testB testA with Interpolate stubbed too.
static void install_test_tables(void)
{
    VtEntry *t[2] = { vt_testa, vt_testb };
    const VtEntry *dt;
    int i, n;

    dt = vt_table(DYNAMICCOLLISIONBODY_VTABLE, &n);
    if (dt == NULL || n != COLLISIONBODY_VT_ENTRIES) {
        fprintf(stderr, "no DynamicCollisionBody table\n");
        exit(2);
    }
    for (i = 0; i < 2; i++) {
        VtEntry *v = t[i];

        memcpy(v, dt, sizeof vt_testa);
        v[VT_SLOT(COLLISIONBODY_VT_GET_POSITION)] =
            (VtEntry){ 8, 0, (VtFn)stub_getpos };
        v[VT_SLOT(COLLISIONBODY_VT_GET_VELOCITY)] =
            (VtEntry){ 8, 0, (VtFn)stub_getvel };
        v[VT_SLOT(COLLISIONBODY_VT_GET_ROTATION)] =
            (VtEntry){ 8, 0, (VtFn)stub_getrot };
        v[VT_SLOT(COLLISIONBODY_VT_ARE_COLLISIONS_ENABLED)] =
            (VtEntry){ 8, 0, (VtFn)stub_enabled };
    }
    vt_testb[VT_SLOT(COLLISIONBODY_VT_INTERPOLATE)] =
        (VtEntry){ 8, 0, (VtFn)stub_interp };
    vt_install(TESTA_VT, vt_testa, COLLISIONBODY_VT_ENTRIES);
    vt_install(TESTB_VT, vt_testb, COLLISIONBODY_VT_ENTRIES);

    // testC: everything Contact calls.
    {
        static const struct { int slot; VtFn fn; } c[] = {
            { COLLISIONBODY_VT_GET_POSITION, (VtFn)e_getpos },
            { COLLISIONBODY_VT_GET_VELOCITY, (VtFn)e_getvel },
            { COLLISIONBODY_VT_GET_ROTATION, (VtFn)e_getrot },
            { COLLISIONBODY_VT_SET_POSITION, (VtFn)e_setpos },
            { COLLISIONBODY_VT_GET_MAX_BACKUP_TIME, (VtFn)e_maxbackup },
            { COLLISIONBODY_VT_MOVE, (VtFn)e_move },
            { COLLISIONBODY_VT_BACKUP, (VtFn)e_backup },
            { COLLISIONBODY_VT_INTERPOLATE, (VtFn)e_interp },
            { COLLISIONBODY_VT_RECOMPUTE_AUXILLIARIES, (VtFn)e_aux },
            { COLLISIONBODY_VT_GET_CURRENT_VELOCITIES, (VtFn)e_curvel },
            { COLLISIONBODY_VT_SET_TO_PHYSICS_MODE, (VtFn)e_physmode },
            { COLLISIONBODY_VT_CONSIDER_IMPULSE, (VtFn)e_consider },
            { COLLISIONBODY_VT_APPLY_IMPULSE, (VtFn)e_apply },
            { COLLISIONBODY_VT_GET_MASS_INVERSE, (VtFn)e_massinv },
            { COLLISIONBODY_VT_GET_INERTIA_TENSOR_INVERSE, (VtFn)e_inertia },
            { COLLISIONBODY_VT_IS_MOVEABLE, (VtFn)e_moveable },
            { COLLISIONBODY_VT_IS_BLINKING, (VtFn)e_blinking },
            { COLLISIONBODY_VT_ARE_COLLISIONS_ENABLED, (VtFn)e_enabled },
            { COLLISIONBODY_VT_GET_BOUNCINESS, (VtFn)e_bounce },
            { COLLISIONBODY_VT_GET_FRICTION, (VtFn)e_friction },
        };

        memcpy(vt_testc, dt, sizeof vt_testc);
        for (i = 0; i < (int)(sizeof c / sizeof c[0]); i++)
            vt_testc[VT_SLOT(c[i].slot)] = (VtEntry){ 8, 0, c[i].fn };
        vt_install(TESTC_VT, vt_testc, COLLISIONBODY_VT_ENTRIES);
    }
    vt_ps[VT_SLOT(PHYSICSSYSTEM_VT_COMPUTE_AUXILIARIES)] =
        (VtEntry){ 4, 0, (VtFn)stub_aux };
    vt_install(PS_VT, vt_ps, 3);
    ps0._vtable = PS_VT;
}

// ------------------------------------------------------------ the ops

static _Alignas(16) uint8_t chunkmem[CHUNK_MAX + 16];

static void print_outm(void)
{
    print_words("  outm", &outm, 16);
    printf("\n");
}

static TrackPolygon *tp_of(uint32_t k)
{
    if ((int)k >= ntps) {
        fprintf(stderr, "no TrackPolygon %u assigned\n", k);
        exit(2);
    }
    return tps[k];
}

static void dyn_step(uint32_t op)
{
    static const uint32_t tables[4] = { DYNAMICCOLLISIONBODY_VTABLE,
                                        TESTA_VT, TESTB_VT, TESTC_VT };
    DynamicCollisionBody *d;
    uint32_t a[16];
    int i;

    switch (op) {
    case OP_DYN_NEW: {
        DynamicCollisionBody *r;

        for (i = 0; i < 4; i++)
            a[i] = next();
        d = dyn(a[0]);
        r = dynamiccollisionbody_init(d, (int32_t)a[1], (int32_t)a[2],
                                      a[3] ? &tc0 : NULL);
        printf("dyn new %s %d %d %s -> %s\n", label(d), (int32_t)a[1],
               (int32_t)a[2], label(a[3] ? &tc0 : NULL), label(r));
        break;
    }
    case OP_DYN_SETVT:
        d = dyn(next());
        d->Body._vtable = tables[next()];
        break;
    case OP_DYN_POKE: {
        uint32_t off, v;
        char *at;

        d = dyn(next());
        off = next();
        v = next();
        if (off == 8) {                 // pPoly, only ever cleared
            if (v != 0) {
                fprintf(stderr, "dyn poke 8 %u\n", v);
                exit(2);
            }
            d->Body.pPoly = NULL;
            break;
        }
        if (off == 84)
            at = (char *)&d->PhysicsMode;
        else if (off >= 100 && off < 256)
            at = (char *)&d->BackupTime + (off - 100);
        else {
            fprintf(stderr, "dyn poke %u\n", off);
            exit(2);
        }
        memcpy(at, &v, 4);
        break;
    }
    case OP_DYN_PTRS:
        d = dyn(next());
        a[0] = next();
        a[1] = next();
        d->pSystem = a[0] ? &ps0 : NULL;
        d->pBody = (int32_t)a[1] >= 0 ? &rbs[a[1]] : NULL;
        break;
    case OP_DYN_SIDE: {
        uint32_t k = next() - REF_D;

        for (i = 0; i < SIDE_WORDS; i++) {
            uint32_t w = next();

            memcpy((char *)&side[k] + 4 * i, &w, 4);
        }
        break;
    }
    case OP_DPOLY:
        for (i = 0; i < 3; i++)
            a[i] = next();
        dpolys[a[0]].NumVertices = (int16_t)a[1];
        for (i = 0; i < (int)a[2]; i++) {
            dverts[a[0]][i].CompressedPosition[0] = fl(next());
            dverts[a[0]][i].CompressedPosition[1] = fl(next());
            dverts[a[0]][i].CompressedPosition[2] = fl(next());
        }
        break;
    case OP_DYN_SETPOLY:
        d = dyn(next());
        d->Body.pPoly = &dpolys[next()];
        break;
    case OP_DYN_BUILD:
        d = dyn(next());
        printf("dyn build %s\n", label(d));
        dynamiccollisionbody_build_bounding_volumes(d);
        break;
    case OP_DYN_UPDATE:
        d = dyn(next());
        printf("dyn update %s\n", label(d));
        dynamiccollisionbody_update_position(d);
        break;
    case OP_DYN_WITNESSES:
        d = dyn(next());
        printf("dyn witnesses %s\n", label(d));
        dynamiccollisionbody_maybe_create_witnesses(d);
        break;
    case OP_DYN_BEGIN:
        d = dyn(next());
        a[0] = next();
        printf("dyn begin %s %08x\n", label(d), a[0]);
        dynamiccollisionbody_begin_move(d, fl(a[0]));
        break;
    case OP_DYN_BACKUP:
        d = dyn(next());
        a[0] = next();
        printf("dyn backup %s %08x\n", label(d), a[0]);
        dynamiccollisionbody_backup(&d->Body, fl(a[0]));
        break;
    case OP_DYN_INTERP:
        d = dyn(next());
        a[0] = next();
        memset(outv, 0x5a, sizeof outv);
        memset(&outm, 0x5a, sizeof outm);
        printf("dyn interp %s %08x\n", label(d), a[0]);
        dynamiccollisionbody_interpolate(&d->Body, &outv[0], &outm,
                                         fl(a[0]));
        print_vec(0, &outv[0]);
        print_outm();
        break;
    case OP_DYN_INTERPV:
        d = dyn(next());
        a[0] = next();
        memset(outv, 0x5a, sizeof outv);
        memset(&outm, 0x5a, sizeof outm);
        printf("dyn interpv %s %08x\n", label(d), a[0]);
        dynamiccollisionbody_interpolate_velocity(d, &outv[0], fl(a[0]));
        print_vec(0, &outv[0]);
        break;
    case OP_DYN_TESTVEL:
        d = dyn(next());
        memset(outv, 0x5a, sizeof outv);
        memset(&outm, 0x5a, sizeof outm);
        printf("dyn testvel %s\n", label(d));
        dynamiccollisionbody_get_test_impulse_velocities(&d->Body, &outv[0],
                                                         &outv[1], &inv[0],
                                                         &inv[1]);
        print_vec(0, &outv[0]);
        print_vec(1, &outv[1]);
        break;
    case OP_RB_SET: {
        uint32_t k = next();
        char *base = (char *)&rbs[k] + RB_FIRST + 2 * RIGIDBODY_SLACK;

        for (i = 0; i < RB_WORDS; i++) {
            uint32_t w = next();

            memcpy(base + 4 * i, &w, 4);
        }
        break;
    }
    case OP_RB_DUMP: {
        uint32_t k = next();
        int o;

        printf("rb RB%u\n", k);
        for (o = RB_FIRST; o < RB_END; o += 32) {
            int n = (RB_END - o) / 4;

            printf("  %d", o);
            print_words("", (char *)&rbs[k] + o + 2 * RIGIDBODY_SLACK,
                        n < 8 ? n : 8);
            printf("\n");
        }
        break;
    }
    case OP_DYN_LOCAL: {
        CollisionBody *first, *last;

        d = dyn(next());
        a[0] = next();
        memset(&first, 0x5a, sizeof first);
        memset(&last, 0x5a, sizeof last);
        dynamiccollisionbody_get_local_collision_bodies(d, fl(a[0]), &first,
                                                        &last);
        printf("dyn local %s %08x -> %s %s\n", label(d), a[0], label(first),
               label(last));
        break;
    }
    case OP_DYN_CREATE_TP:
        d = dyn(next());
        printf("dyn create tp %s\n", label(d));
        i = dynamiccollisionbody_create_track_polygon_collision_bodies(d);
        printf("  -> %d\n", i);
        break;
    case OP_DYN_TPCHECK: {
        TrackPolygon *tp;

        d = dyn(next());
        tp = tp_of(next());
        printf("dyn tpcheck %s %s\n", label(d), label(tp));
        i = dynamiccollisionbody_track_polygon_check(d, tp);
        printf("  -> %d\n", i);
        break;
    }
    case OP_TP_ASSIGN: {
        TrackPolygon *tp;

        a[0] = next();
        if (ntps >= NTPS) {
            fprintf(stderr, "too many TrackPolygons assigned\n");
            exit(2);
        }
        tp = topotree_assign(&TheTopologyTree,
                             &TheTopologyTree.pPolygonTable[a[0]]);
        tps[ntps++] = tp;
        printf("tp assign %u -> %s\n", a[0], label(tp));
        break;
    }
    case OP_TP_GEOM: {
        TrackPolygon *tp = tp_of(next());

        for (i = 0; i < 8; i++)
            a[i] = next();
        tp->BBoxMin.x = fl(a[0]);
        tp->BBoxMin.y = fl(a[1]);
        tp->BBoxMax.x = fl(a[2]);
        tp->BBoxMax.y = fl(a[3]);
        tp->Normal.x = fl(a[4]);
        tp->Normal.y = fl(a[5]);
        tp->Normal.z = fl(a[6]);
        tp->PlaneDistance = fl(a[7]);
        break;
    }
    case OP_TC_SET: {
        uint32_t n = next();

        tc0.TotalNumTrackPolygons = (int32_t)n;
        for (i = 0; i < (int)n; i++)
            tc0.TrackPolygonTable[i] = tp_of(next());
        break;
    }
    case OP_SMOKE: {
        CollisionBody *from, *to;

        a[0] = next();
        a[1] = next();
        from = body(a[0]);
        to = (int32_t)a[1] >= 0 ? body(a[1]) : NULL;
        for (i = 0; i < nsmoke && smoke_from[i] != from; i++)
            ;
        if (i == NSMOKE) {
            fprintf(stderr, "too many smokeables\n");
            exit(2);
        }
        if (i == nsmoke)
            nsmoke++;
        smoke_from[i] = from;
        smoke_to[i] = to;
        break;
    }
    case OP_DYN_DTOR:
        d = dyn(next());
        a[0] = next();
        printf("dyn dtor %s %d\n", label(d), (int32_t)a[0]);
        dynamiccollisionbody_destroy(d, (int32_t)a[0]);
        break;
    case OP_DYN_BBOX:
        d = dyn(next());
        memset(outv, 0x5a, sizeof outv);
        memset(&outm, 0x5a, sizeof outm);
        printf("dyn bbox %s\n", label(d));
        dynamiccollisionbody_get_bounding_box(d, &outv[0], &outv[1]);
        print_vec(0, &outv[0]);
        print_vec(1, &outv[1]);
        break;
    case OP_TP_FILL: {
        TopologyTreePolygon *p;
        int made = 0;

        a[0] = next();
        a[1] = next();
        p = &TheTopologyTree.pPolygonTable[a[0]];
        while (TrackPolygonCollisionBodySlotPool->numAllocatedSlots
               < (int)a[1]) {
            void *m = trackpolygoncollisionbody_new();

            if (m == NULL) {
                fprintf(stderr, "TP_FILL past the pool\n");
                exit(2);
            }
            trackpolygoncollisionbody_init(m, -1, p);
            made++;
        }
        printf("tp fill %u %u -> %d\n", a[0], a[1], made);
        break;
    }
    default:
        fprintf(stderr, "bad op %u at word %zu\n", op, rd - 1);
        exit(2);
    }
}

typedef void (*FnMove)(void *, float);
typedef void (*FnApply)(void *, bVector3 *, bVector3 *);
typedef void (*FnPhysMode)(void *, CollisionBody *);

static const VtEntry *car_slot(CollisionBody *b, int slot, void **self)
{
    const VtEntry *e = vt_slot(b->_vtable, slot);

    *self = vt_this(b, e);
    return e;
}

static void car_step(uint32_t op)
{
    CollisionBody *b;
    CarCollisionBody *c;
    const VtEntry *e;
    void *self;
    uint32_t a[24];
    int i, k;

    switch (op) {
    case OP_CAR_NEW: {
        void *m;

        k = (int)next();
        printf("car new CAR%d\n", k);
        m = carcollisionbody_new();
        printf("  new %s\n", label(m));
        if (m != NULL)
            printf("  -> %s\n", label(carcollisionbody_init(m, &cars[k])));
        break;
    }
    case OP_CAR_DTOR:
        c = (CarCollisionBody *)body(next());
        a[0] = next();
        printf("car dtor %s %d\n", label(c), (int32_t)a[0]);
        carcollisionbody_destroy(c, (int32_t)a[0]);
        break;
    case OP_CAR_FIELD: {
        Car *car;

        k = (int)next();
        a[0] = next();
        a[1] = next();
        car = &cars[k];
        switch (a[0]) {
        case CF_DRIVER:
            car->DriverNumber = (int16_t)a[1];
            break;
        case CF_NAME:
            memset(ctis[k].BaseModelName, 0, sizeof ctis[k].BaseModelName);
            strcpy(ctis[k].BaseModelName, car_names[a[1]]);
            break;
        case CF_PLAYER:
            car->pPlayer = a[1] ? &pl0 : NULL;
            break;
        case CF_MODE:
            car->TheMovementMode = (MovementMode)a[1];
            break;
        case CF_MOVER:
            car->pCarMover = a[1] == 0 ? NULL
                           : a[1] == 1 ? (CarMover *)(void *)&m0
                                       : (CarMover *)(void *)&m1;
            break;
        case CF_ANIM:
            car->pAnimatedDriver = a[1] ? (AnimatedDriver *)(void *)ad0
                                        : NULL;
            break;
        case CF_DAMAGE:
            car->pCarDamage = a[1] ? (CarDamage *)(void *)dmg0 : NULL;
            break;
        case CF_BLINK:
            blink[k] = (int32_t)a[1];
            break;
        case CF_POOF:
            poof[k] = (int32_t)a[1];
            break;
        default:
            fprintf(stderr, "car field %u\n", a[0]);
            exit(2);
        }
        break;
    }
    case OP_CAR_SIDE: {
        CarState *s = &cars[next()].State;

        for (i = 0; i < SIDE_WORDS; i++)
            a[i] = next();
        memcpy(&s->Position, a, 16);
        memcpy(&s->Velocity, a + 4, 16);
        memcpy(&s->BodyMatrix, a + 8, 64);
        break;
    }
    case OP_CAR_COG:
        k = (int)next();
        for (i = 0; i < 4; i++)
            a[i] = next();
        memcpy(&ctis[k].CenterOfGravity, a, 16);
        break;
    case OP_GLOBAL:
        a[0] = next();
        a[1] = next();
        switch (a[0]) {
        case G_BORING:
            BoringAIForCameraTuningOn = (int32_t)a[1];
            break;
        case G_WILLIAMS:
            WilliamsAITuningMode = (int32_t)a[1];
            break;
        case G_RC:
            pRaceCoordinator = a[1] ? (RaceCoordinator *)(void *)rc0 : NULL;
            break;
        case G_STATE:
            rc0[0] = (int32_t)a[1];
            break;
        case G_COP:
            pCopManager = a[1] ? (tCopManager *)(void *)cop0 : NULL;
            break;
        case G_TIMER:
            WorldTimer = (int32_t)a[1];
            break;
        case G_PORT:
            pl0.JoyPort = (JoystickPort)a[1];
            break;
        case G_SEAMS:                   // the 3DS build leaves both unset
            gPortRumbleImpactFn = (a[1] & 1) ? NULL : stub_rumble;
            gCarStartForceImpactFn = (a[1] & 2) ? NULL : stub_force;
            break;
        case G_PRINT:
            PrintThisTime = (int32_t)a[1];
            break;
        case G_LOOP:
            WorldLoopCounter = (int32_t)a[1];
            break;
        case G_THRESH:
            ContactThreshold = fl(a[1]);
            break;
        case G_BIAS:
            WaferBias = fl(a[1]);
            break;
        case G_MINFACTOR:
            MinimumContactImpulseFactor = fl(a[1]);
            break;
        case G_MINSPEED:
            MinimumContactImpulseSpeed = fl(a[1]);
            break;
        case G_SCRAPE:
            MaxFrictionScrapeSpeed = fl(a[1]);
            break;
        default:
            fprintf(stderr, "global %u\n", a[0]);
            exit(2);
        }
        break;
    case OP_PP: {
        PipelinePolyhedron *pp;
        VCPolyhedron *p;

        k = (int)next();
        pp = &pps[k];
        p = &pp->Poly;
        pp->NameHash = next();
        pp->CenterOfGravityFixed = (int32_t)next();
        a[0] = next();
        p->NumVertices = (int16_t)a[0];
        for (i = 0; i < (int)a[0]; i++) {
            ppverts[k][i].CompressedPosition[0] = fl(next());
            ppverts[k][i].CompressedPosition[1] = fl(next());
            ppverts[k][i].CompressedPosition[2] = fl(next());
        }
        if (!pp_linked[k]) {            // at the tail, as the loader links
            p->Link.prev = PipelinePolyhedronList.prev;
            ((VCPolyhedronNode *)(void *)PipelinePolyhedronList.prev)->next =
                p;
            PipelinePolyhedronList.prev = p;
            p->Link.next = (VCPolyhedron *)(void *)&PipelinePolyhedronList;
            pp_linked[k] = 1;
        }
        break;
    }
    case OP_CAR_MOVE:
        b = body(next());
        a[0] = next();
        a[1] = next();
        if (a[1] > NMOVE) {
            fprintf(stderr, "car move queue of %u\n", a[1]);
            exit(2);
        }
        for (i = 0; i < (int)a[1]; i++)
            move_q[i] = next();
        move_n = (int)a[1];
        move_at = 0;
        printf("car move %s %08x\n", label(b), a[0]);
        e = car_slot(b, COLLISIONBODY_VT_MOVE, &self);
        ((FnMove)e->fn)(self, fl(a[0]));
        move_n = move_at = 0;
        break;
    case OP_CAR_APPLY:
        b = body(next());
        for (i = 0; i < 8; i++)
            a[i] = next();
        memcpy(cv, a, 32);
        printf("car apply %s\n", label(b));
        e = car_slot(b, COLLISIONBODY_VT_APPLY_IMPULSE, &self);
        ((FnApply)e->fn)(self, &cv[0], &cv[1]);
        break;
    case OP_CAR_DAMAGE:
    case OP_CAR_ANIM:
        c = (CarCollisionBody *)body(next());
        for (i = 0; i < 5; i++)
            a[i] = next();
        memcpy(&cv[0], a, 16);
        printf("car %s %s %08x\n", op == OP_CAR_DAMAGE ? "damage" : "anim",
               label(c), a[4]);
        if (op == OP_CAR_DAMAGE)
            carcollisionbody_add_damage(c, &cv[0], fl(a[4]));
        else
            carcollisionbody_animate_collision_reaction(c, &cv[0], fl(a[4]));
        break;
    case OP_CAR_TIMES: {
        Timer t;

        c = (CarCollisionBody *)body(next());
        a[0] = next();
        a[1] = next();
        t.PackedTime = a[0];
        carcollisionbody_set_last_penetration_time(c, &t);
        t.PackedTime = a[1];
        carcollisionbody_set_last_yaw_control_collision_time(c, &t);
        printf("car times %s -> pen %08x yaw %08x car %s\n", label(c),
               carcollisionbody_get_last_penetration_time(c).PackedTime,
               carcollisionbody_get_last_yaw_control_collision_time(c)
                   .PackedTime,
               label(carcollisionbody_get_car(c)));
        break;
    }
    case OP_CAR_STPM: {
        CollisionBody *other;
        DynamicCollisionBody *d;

        b = body(next());
        a[0] = next();
        other = (int32_t)a[0] >= 0 ? body(a[0]) : NULL;
        printf("car stpm %s %s\n", label(b), label(other));
        e = car_slot(b, COLLISIONBODY_VT_SET_TO_PHYSICS_MODE, &self);
        ((FnPhysMode)e->fn)(self, other);
        d = (DynamicCollisionBody *)b;
        printf("  -> sys %s rb %s\n", label(d->pSystem), label(d->pBody));
        break;
    }
    default:
        fprintf(stderr, "bad op %u at word %zu\n", op, rd - 1);
        exit(2);
    }
}

// ------------------------------------------------------------ the contacts

// A contact operand: a slot of the pool, the nth on clist from REF_LIST,
// or the one CT_NEW made last.
static Contact *newest;

static Contact *contact_of(uint32_t x)
{
    const Contact *end = (const Contact *)(const void *)&clist;
    Contact *c;
    uint32_t n;

    if (x == REF_NEWEST && newest != NULL)
        return newest;
    if (x >= REF_LIST && x < REF_NEWEST) {
        c = clist.next;
        for (n = x - REF_LIST; c != end && n > 0; n--)
            c = c->Link.next;
        if (c != end)
            return c;
    } else if (x < REF_LIST && ContactSlotPool != NULL) {
        return (Contact *)bGetSlot(ContactSlotPool, (int)x);
    }
    fprintf(stderr, "no contact %#x\n", x);
    exit(2);
}

static void read_words(void *p, int n)
{
    uint32_t w;
    int i;

    for (i = 0; i < n; i++) {
        w = next();
        memcpy((char *)p + 4 * i, &w, 4);
    }
}

static void dump_contacts(void)
{
    const Contact *end = (const Contact *)(const void *)&clist;
    const Contact *c;
    int n;

    printf("  clist");
    n = 0;
    for (c = clist.next; c != end && n < MAX_WALK; c = c->Link.next, n++)
        printf(" %s", label(c));
    printf(" |");
    n = 0;
    for (c = clist.prev; c != end && n < MAX_WALK; c = c->Link.prev, n++)
        printf(" %s", label(c));
    printf("\n");
    n = 0;
    for (c = clist.next; c != end && n < MAX_WALK; c = c->Link.next, n++) {
        printf("  contact %s bt %08x b1 %s b2 %s wit %s cv", label(c),
               bits(c->BackupTime), label(c->pBody1), label(c->pBody2),
               label(c->pWitness));
        print_words("", &c->CrowbarVector, 4);
        printf(" lf %d\n", c->LoopFound);
    }
    dump_pool("contact", ContactSlotPool);
}

static void ct_step(uint32_t op)
{
    CollisionBodyWitness *w;
    Contact *c;
    uint32_t a[8];
    int k;

    switch (op) {
    case OP_E_STATE:
        k = (int)next();
        read_words(&es[k], E_WORDS);
        break;
    case OP_E_QUEUE: {
        int i;

        k = (int)next();
        es[k].nq = (int)next();
        es[k].atq = 0;
        for (i = 0; i < es[k].nq; i++)
            es[k].q[i] = next();
        break;
    }
    case OP_BOX: {
        float f[6];
        int i;

        k = (int)next();
        for (i = 0; i < 6; i++)
            f[i] = fl(next());
        rectpoly_init(&boxes[k], f[0], f[1], f[2], f[3], f[4], f[5]);
        break;
    }
    case OP_BOX_SET: {
        CollisionBody *b = body(next());

        b->pPoly = &boxes[next()].Poly;
        break;
    }
    case OP_TP_VERTS:
        read_words(tp_of(next())->Vertices, 16);
        break;
    case OP_CT_INIT:
        printf("ct init\n");
        init_contact();
        break;
    case OP_CT_CLOSE:
        printf("ct close\n");
        close_contact();
        break;
    case OP_CT_TEST:
        a[0] = next();
        printf("ct test W%u\n", a[0]);
        cbwitness_test_for_contact(witness(a[0]), &clist);
        printf("  print %d\n", PrintThisTime);
        break;
    case OP_CT_RESOLVE:
        c = contact_of(next());
        printf("ct resolve %s\n", label(c));
        contact_resolve(c);
        break;
    case OP_CT_REMOVE: {
        CollisionBody *b = body(next());

        printf("ct remove %s\n", label(b));
        contact_remove_contacts(&clist, b);
        break;
    }
    case OP_CT_DUMP:
        printf("ct dump\n");
        dump_contacts();
        break;
    case OP_CT_NEW:
        a[0] = next();
        w = witness(a[0]);
        printf("ct new W%u\n", a[0]);
        c = bSlotOMalloc(ContactSlotPool);
        printf("  new %s\n", label(c));
        newest = c;
        c = contact_init(c, w->pBody1, w->pBody2, w);
        printf("  -> %s\n", label(c));
        break;
    case OP_CT_TIME: {
        float t;

        c = contact_of(next());
        printf("ct time %s\n", label(c));
        t = contact_find_contact_time(c);
        printf("  -> %08x cv", bits(t));
        print_words("", &c->CrowbarVector, 4);
        printf("\n");
        break;
    }
    case OP_CT_CROWBAR:
        c = contact_of(next());
        a[1] = next();
        printf("ct crowbar %s %08x\n", label(c), a[1]);
        contact_crowbar(c, fl(a[1]));
        print_words("  cv", &c->CrowbarVector, 4);
        printf("\n");
        break;
    case OP_CT_POINT:
        c = contact_of(next());
        printf("ct point %s\n", label(c));
        memset(outv, 0x5a, sizeof outv);
        contact_find_contact_point_and_normal(c, &outv[0], &outv[1]);
        print_vec(0, &outv[0]);
        print_vec(1, &outv[1]);
        break;
    case OP_CT_PLANAR:
        c = contact_of(next());
        memset(outv, 0x5a, sizeof outv);
        read_words(&outv[0], 4);
        printf("ct planar %s\n", label(c));
        contact_find_planar_collision_contact_point(c, &outv[0]);
        print_vec(0, &outv[0]);
        break;
    case OP_CT_IMPULSE:
        c = contact_of(next());
        printf("ct impulse %s\n", label(c));
        contact_collision_impulse(c);
        break;
    case OP_CT_CPV:
        read_words(ctv, 12);
        memset(outv, 0x5a, sizeof outv);
        printf("ct cpv\n");
        get_contact_point_velocity(&outv[0], &ctv[0], &ctv[1], &ctv[2]);
        print_vec(0, &outv[0]);
        break;
    case OP_CT_DENOM:
        read_words(&ctm, 16);
        read_words(ctv, 8);
        printf("ct denom -> %08x\n", bits(denominator_term(&ctm, &ctv[0],
                                                           &ctv[1])));
        break;
    case OP_CT_WAFER: {
        CollisionBody *t = body(next());
        DynamicCollisionBody *d = dyn(next());

        printf("ct wafer %s %s\n", label(t), label(d));
        memset(outv, 0x5a, sizeof outv);
        find_wafer_normal(&outv[0], (TrackPolygonCollisionBody *)t, d);
        print_vec(0, &outv[0]);
        break;
    }
    case OP_CT_SORT: {
        Contact *d;

        c = contact_of(next());
        d = contact_of(next());
        printf("ct sort %s %s -> %d\n", label(c), label(d),
               contact_time_sorting(c, d));
        break;
    }
    case OP_CT_GETCOLL: {
        struct Collision *r;

        a[0] = next();
        w = witness(a[0]);
        read_words(&ctv[0], 4);
        printf("ct getcoll W%u\n", a[0]);
        r = cbwitness_get_collision(w, &ctv[0]);
        printf("  -> %s\n", label(r));
        break;
    }
    case OP_CT_BEGIN:
        a[0] = next();
        w = witness(a[0]);
        read_words(&ctv[0], 4);
        printf("ct begin W%u\n", a[0]);
        cbwitness_begin_collision(w, &ctv[0]);
        printf("  -> %s\n", label(w->pCollision));
        break;
    case OP_CT_DEL:
        c = contact_of(next());
        a[1] = next();
        printf("ct del %s %d\n", label(c), (int32_t)a[1]);
        contact_destroy(c, (int32_t)a[1]);
        break;
    case OP_CT_POKE:
        c = contact_of(next());
        a[0] = next();
        a[1] = next();
        if (a[0] == XF_BT)
            c->BackupTime = fl(a[1]);
        else if (a[0] < XF_LF)
            memcpy((char *)&c->CrowbarVector + 4 * (a[0] - XF_CV), &a[1], 4);
        else if (a[0] == XF_LF)
            c->LoopFound = (int32_t)a[1];
        else {
            fprintf(stderr, "ct poke %u\n", a[0]);
            exit(2);
        }
        break;
    case OP_CT_LINK: {
        Contact *end = (Contact *)(void *)&clist;

        c = contact_of(next());
        c->Link.prev = clist.prev;
        c->Link.next = end;
        ((ContactNode *)(void *)clist.prev)->next = c;
        clist.prev = c;
        break;
    }
    case OP_WIT_CP:
        w = witness(next());
        read_words(&w->Witness.CP1, 4);
        read_words(&w->Witness.CP2, 4);
        break;
    default:
        fprintf(stderr, "bad op %u at word %zu\n", op, rd - 1);
        exit(2);
    }
}

static void step(uint32_t op)
{
    uint32_t a[16];
    int i;

    switch (op) {
    case OP_TAG:
        printf("[%u]\n", next());
        break;
    case OP_STATIC_INIT:
        printf("static init\n");
        collisionbody_static_init();
        break;
    case OP_STATIC_CLOSE:
        printf("static close\n");
        collisionbody_static_close();
        break;
    case OP_INIT:
        printf("init\n");
        init_collision_body();
        break;
    case OP_CLOSE:
        printf("close\n");
        close_collision_body();
        break;
    case OP_TREE_INIT:
        printf("tree init\n");
        topotree_init_tree(&TheTopologyTree);
        break;
    case OP_TREE_CLOSE:
        printf("tree close\n");
        topotree_close_tree(&TheTopologyTree);
        break;
    case OP_TREE_LOAD: {
        uint32_t n = next();
        int r;

        if ((size_t)n * 4 > CHUNK_MAX) {
            fprintf(stderr, "chunk too big\n");
            exit(2);
        }
        for (i = 0; i < (int)n; i++) {
            uint32_t w = next();

            memcpy(chunkmem + 8 + 4 * (size_t)i, &w, 4);
        }
        r = topotree_loader(&TheTopologyTree, chunkmem + 8);
        printf("tree load -> %d polys %d\n", r, TheTopologyTree.NumPolygons);
        break;
    }
    case OP_FILL_H:
        a[0] = next();
        a[1] = next();
        if (a[0] < NH)
            memset(&hbody[a[0]], (int)a[1], sizeof hbody[0]);
        else
            memset(dyn(a[0]), (int)a[1], sizeof dbody[0]);
        break;
    case OP_BASE_NEW:
        for (i = 0; i < 3; i++)
            a[i] = next();
        printf("base new H%u %d %d -> %s\n", a[0], (int32_t)a[1],
               (int32_t)a[2], label(collisionbody_init(body(a[0]),
                                                       (int32_t)a[1],
                                                       (int32_t)a[2])));
        break;
    case OP_STATIC_NEW:
        for (i = 0; i < 3; i++)
            a[i] = next();
        printf("static new H%u %d %d -> %s\n", a[0], (int32_t)a[1],
               (int32_t)a[2],
               label(staticcollisionbody_init(&hbody[a[0]], (int32_t)a[1],
                                              (int32_t)a[2])));
        break;
    case OP_TP_NEW: {
        void *m;

        a[0] = next();
        a[1] = next();
        printf("tp new %d poly %u\n", (int32_t)a[0], a[1]);
        m = trackpolygoncollisionbody_new();
        printf("  new %s\n", label(m));
        if (m != NULL)
            printf("  -> %s\n", label(trackpolygoncollisionbody_init(
                                    m, (int32_t)a[0],
                                    &TheTopologyTree.pPolygonTable[a[1]])));
        break;
    }
    case OP_VDEL: {
        CollisionBody *b;
        const VtEntry *e;

        a[0] = next();
        a[1] = next();
        b = body(a[0]);
        printf("vdel %s %d\n", label(b), (int32_t)a[1]);
        e = vt_slot(b->_vtable, COLLISIONBODY_VT_DESTROY);
        ((FnVD)e->fn)(vt_this(b, e), (int32_t)a[1]);
        break;
    }
    case OP_DTOR: {
        CollisionBody *b;

        for (i = 0; i < 3; i++)
            a[i] = next();
        b = body(a[0]);
        printf("dtor %s %u %d\n", label(b), a[1], (int32_t)a[2]);
        if (a[1] == 0)
            collisionbody_destroy(b, (int32_t)a[2]);
        else if (a[1] == 1)
            staticcollisionbody_destroy((StaticCollisionBody *)b,
                                        (int32_t)a[2]);
        else
            trackpolygoncollisionbody_destroy((TrackPolygonCollisionBody *)b,
                                              (int32_t)a[2]);
        break;
    }
    case OP_SET_POLY:
        a[0] = next();
        a[1] = next();
        body(a[0])->pPoly = &polys[a[1]];
        break;
    case OP_SETBOX: {
        bVector2 mn, mx;
        CollisionBody *b;

        for (i = 0; i < 5; i++)
            a[i] = next();
        b = body(a[0]);
        mn.x = fl(a[1]);
        mn.y = fl(a[2]);
        mx.x = fl(a[3]);
        mx.y = fl(a[4]);
        printf("setbox %s %08x %08x %08x %08x\n", label(b), a[1], a[2], a[3],
               a[4]);
        collisionbody_set_bbox_min_max(b, &mn, &mx);
        break;
    }
    case OP_RAWBOX: {
        CollisionBody *b;

        for (i = 0; i < 5; i++)
            a[i] = next();
        b = body(a[0]);
        b->BBoxMin.x = fl(a[1]);
        b->BBoxMin.y = fl(a[2]);
        b->BBoxMax.x = fl(a[3]);
        b->BBoxMax.y = fl(a[4]);
        break;
    }
    case OP_UPDW:
        a[0] = next();
        a[1] = next();
        collisionbody_update_max_width(body(a[0]), fl(a[1]));
        printf("updw %s %08x -> %08x\n", label(body(a[0])), a[1],
               bits(MaxCollisionBodyWidthX));
        break;
    case OP_SETMAXW:
        MaxCollisionBodyWidthX = fl(next());
        break;
    case OP_FLIP:
        a[0] = next();
        a[1] = next();
        printf("flip %s %s -> %d\n", label(body(a[0])), label(body(a[1])),
               collisionbody_flip_function(body(a[0]), body(a[1])));
        break;
    case OP_NAME: {
        char src[48];
        CollisionBody *b;

        a[0] = next();
        for (i = 0; i < 12; i++) {
            uint32_t w = next();

            memcpy(src + 4 * i, &w, 4);
        }
        b = body(a[0]);
        printf("name %s\n", label(b));
        collisionbody_set_debug_name(b, src);
        break;
    }
    case OP_FIND:
        a[0] = next();
        printf("find %d -> %s\n", (int32_t)a[0],
               label(collisionbody_find((int32_t)a[0])));
        break;
    case OP_NEXTID:
        printf("nextid -> %d\n", collisionbody_get_next_id());
        break;
    case OP_GETCOLL:
        a[0] = next();
        a[1] = next();
        printf("getcoll %s %d -> %s\n", label(body(a[0])), (int32_t)a[1],
               label(collisionbody_get_collision(body(a[0]),
                                                 (int32_t)a[1])));
        break;
    case OP_ENABLE:
        a[0] = next();
        printf("enable %s\n", label(body(a[0])));
        collisionbody_enable_collisions(body(a[0]));
        break;
    case OP_DISABLE:
        a[0] = next();
        printf("disable %s\n", label(body(a[0])));
        collisionbody_disable_collisions(body(a[0]));
        break;
    case OP_BBOX: {
        bVector2 mn, mx;

        for (i = 0; i < 6; i++)
            a[i] = next();
        mn.x = fl(a[1]);
        mn.y = fl(a[2]);
        mx.x = fl(a[3]);
        mx.y = fl(a[4]);
        printf("bbox %s %08x %08x %08x %08x %08x -> %d\n", label(body(a[0])),
               a[1], a[2], a[3], a[4], a[5],
               collisionbody_do_bbox_check(body(a[0]), &mn, &mx, fl(a[5])));
        break;
    }
    case OP_BBOXB:
        for (i = 0; i < 3; i++)
            a[i] = next();
        printf("bboxb %s %s %08x -> %d\n", label(body(a[0])),
               label(body(a[1])), a[2],
               collisionbody_do_bbox_check_body(body(a[0]), body(a[1]),
                                                fl(a[2])));
        break;
    case OP_SETB: {
        CollisionBody *b;

        for (i = 0; i < 3; i++)
            a[i] = next();
        b = body(a[0]);
        switch (a[1]) {
        case 12: b->Type = (int8_t)a[2]; break;
        case 13: b->Dynamic = (int8_t)a[2]; break;
        case 16: b->NumWitnesses = (int8_t)a[2]; break;
        case 17: b->CollisionsDisabled = (int8_t)a[2]; break;
        case 18: b->NumCollisions = (int8_t)a[2]; break;
        case 19: b->ActiveCollisionDetection = (int8_t)a[2]; break;
        default:
            fprintf(stderr, "setb %u\n", a[1]);
            exit(2);
        }
        break;
    }
    case OP_NA_SET:
        a[0] = next();
        printf("na set %d\n", (int32_t)a[0]);
        numberallocator_set_max_numbers(&na, (int32_t)a[0]);
        break;
    case OP_NA_ALLOC:
        printf("na alloc -> %d\n", numberallocator_allocate(&na));
        break;
    case OP_NA_ALLOCN:
        a[0] = next();
        printf("na allocn %d\n", (int32_t)a[0]);
        numberallocator_allocate_number(&na, (int32_t)a[0]);
        break;
    case OP_NA_FREE:
        a[0] = next();
        printf("na free %d\n", (int32_t)a[0]);
        numberallocator_free_number(&na, (int32_t)a[0]);
        break;
    case OP_NA_DESTROY:
        a[0] = next();
        printf("na destroy %d\n", (int32_t)a[0]);
        numberallocator_destroy(&na, (int32_t)a[0]);
        break;
    case OP_NA_DUMP:
        printf("na max %d lowest %d field %s\n", na.MaxNumbers,
               na.LowestFreeNumber, label(na.pAllocatedBitField));
        if (na.pAllocatedBitField != NULL && na.MaxNumbers > 0)
            dump_bits("   ", na.pAllocatedBitField, (na.MaxNumbers >> 3) + 1);
        break;
    case OP_WIT_NEW: {
        void *m;

        a[0] = next();
        a[1] = next();
        printf("wit new %s %s\n", label(body(a[0])), label(body(a[1])));
        m = bSlotOMalloc(CollisionBodyWitnessSlotPool);
        printf("  new %s\n", label(m));
        printf("  -> %s\n", label(cbwitness_init(m, body(a[0]),
                                                 body(a[1]))));
        break;
    }
    case OP_WIT_DEL:
        a[0] = next();
        a[1] = next();
        printf("wit del %s %d\n", label(witness(a[0])), (int32_t)a[1]);
        cbwitness_destroy(witness(a[0]), (int32_t)a[1]);
        break;
    case OP_WIT_SETCOLL:
        a[0] = next();
        a[1] = next();
        witness(a[0])->pCollision =
            a[1] == 0 ? NULL : (struct Collision *)(void *)colls[a[1] - 1];
        break;
    case OP_WIT_END:
        a[0] = next();
        printf("wit end %s\n", label(witness(a[0])));
        cbwitness_end_collision(witness(a[0]));
        break;
    case OP_EXPIRED:
        a[0] = next();
        printf("expired %s -> %d\n", label(witness(a[0])),
               cbwitness_has_expired(witness(a[0])));
        break;
    case OP_EXISTS:
        a[0] = next();
        a[1] = next();
        printf("exists %s %s -> %d\n", label(body(a[0])), label(body(a[1])),
               cbwitness_does_witness_exist(body(a[0]), body(a[1])));
        break;
    case OP_YAW:
        a[0] = next();
        printf("yaw %s -> %d\n", label(body(a[0])),
               is_yaw_control_inducing_collision_body(body(a[0])));
        break;
    case OP_ELIM:
        printf("elim\n");
        cbwitness_eliminate_all();
        break;
    case OP_VCALL:
        a[0] = next();
        a[1] = next();
        vcall(body(a[0]), (int)a[1]);
        break;
    case OP_VTDUMP:
        vt_dump();
        break;
    case OP_DUMP:
        dump();
        break;
    case OP_STAT:
        a[0] = next();
        a[1] = next();
        ((int32_t *)&TheCollisionStats)[a[0]] = (int32_t)a[1];
        break;
    case OP_TPPOKE: {
        TrackPolygon *tp;

        for (i = 0; i < 3; i++)
            a[i] = next();
        tp = (TrackPolygon *)bGetSlot(TrackPolygonSlotPool, (int)a[0]);
        if (a[1] == 10)
            tp->Flags = (uint8_t)a[2];
        else
            tp->TheTerrainType = (uint8_t)a[2];
        break;
    }
    case OP_ACCESS: {
        CollisionBody *b;

        a[0] = next();
        b = body(a[0]);
        printf("access %s vt %s max %s min %s nc %d poly %s name %s act %d "
               "id %d dyn %d",
               label(b), vtname(b->_vtable),
               collisionbody_get_bbox_max(b) == &b->BBoxMax ? "ok"
                                                                     : "?",
               collisionbody_get_bbox_min(b) == &b->BBoxMin ? "ok" : "?",
               collisionbody_get_num_collisions(b),
               label(collisionbody_get_poly(b)),
               collisionbody_get_debug_name(b) == b->DebugName ? "name" : "?",
               collisionbody_does_active_collision_detection(b),
               collisionbody_get_id(b), collisionbody_is_dynamic(b));
        if (b->_vtable == TRACKPOLYGONCOLLISIONBODY_VTABLE)
            printf(" tp %s", label(trackpolygoncollisionbody_get_track_polygon(
                                 (TrackPolygonCollisionBody *)b)));
        printf("\n");
        break;
    }
    default:
        if (op >= OP_E_STATE && op < OP_COUNT) {
            ct_step(op);
            break;
        }
        if (op >= OP_CAR_NEW && op < OP_COUNT) {
            car_step(op);
            break;
        }
        if (op >= OP_DYN_NEW && op < OP_COUNT) {
            dyn_step(op);
            break;
        }
        fprintf(stderr, "bad op %u at word %zu\n", op, rd - 1);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    FILE *fh;
    long len;
    int i;

    if (argc != 2) {
        fprintf(stderr, "usage: collisionbody_test ops.bin\n");
        return 2;
    }
    fh = fopen(argv[1], "rb");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    fseek(fh, 0, SEEK_END);
    len = ftell(fh);
    fseek(fh, 0, SEEK_SET);
    words = malloc((size_t)len + 4);
    nwords = (size_t)len / 4;
    if (fread(words, 4, nwords, fh) != nwords) {
        fprintf(stderr, "short read\n");
        return 2;
    }
    fclose(fh);
    if (getenv("CB_TEST_UNBUFFERED") != NULL)
        setvbuf(stdout, NULL, _IONBF, 0);

    bSlotPoolManagerInit();
    bSetSlotPoolAllocator(arena_alloc, arena_release);
    bSetSlotPoolPrintf(printf_hook);
    bSetMemoryHooks(hook_malloc, hook_free);
    track_static_init();
    collisionbody_install_vtables();
    gCollisionDestroyFn = coll_destroy;
    gConvertToSmokeableFn = stub_smoke;
    install_test_tables();
    for (i = 0; i < NPOLY; i++) {
        vcpoly_init(&polys[i]);
        polys[i].pVertices = pverts[i];
    }
    for (i = 0; i < NDPOLY; i++) {
        vcpoly_init(&dpolys[i]);
        dpolys[i].pVertices = dverts[i];
    }

    polyhedra_init_globals();
    carcollisionbody_install_vtable();
    gCarDamageAddDamageFn = stub_add_damage;
    gCopManagerMonitorImpactFn = stub_monitor;
    gAnimatedDriverBeginCollisionFn = stub_begin;
    gPortRumbleImpactFn = stub_rumble;
    gCarStartForceImpactFn = stub_force;
    for (i = 0; i < NCAR; i++)
        cars[i].pCarTypeInfo = &ctis[i];
    m0.pBody = &rbs[1];
    m1.pBody = &rbs[0];
    // Only the links, the count and the vertex pointer are ever read.
    for (i = 0; i < NPP; i++)
        pps[i].Poly.pVertices = ppverts[i];
    gCollisionNewFn = coll_new;
    gCollisionAddImpulseFn = coll_add_impulse;
    clist.next = clist.prev = (Contact *)(void *)&clist;

    while (rd < nwords)
        step(next());
    fflush(stdout);
    return 0;
}
