// Harness for tools/smokeable_check.py: runs the checker's script on
// smokeable.c and smokeableinfo.c -- the Smokeables, their virgins, the
// module's spawning and clearing, and chunk slot 27's loader -- and prints
// what the model prints for the retail image. See the checker's docstring.
//
//     smokeable_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "acidsys.h"
#include "bmath.h"
#include "bmatrix.h"
#include "bmem.h"
#include "bplist.h"
#include "bslotpool.h"
#include "collision.h"
#include "collisionbody.h"
#include "collisionsound.h"
#include "emath.h"
#include "physcomp.h"
#include "physicssystem.h"
#include "polyhedra.h"
#include "race.h"
#include "realtime.h"
#include "rigidbody.h"
#include "scenery.h"
#include "smokeable.h"
#include "terraintype.h"
#include "topology.h"
#include "vclip.h"
#include "vtable.h"
#include "world.h"
#include "worldobject.h"

#define NCARS      2
#define RETAIL_RECT_SIZE 2800
#define RETAIL_SYSTEM_OFFSET 256        // offsetof(Smokeable, System)

static uint32_t fb(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float bf(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static uint32_t hex(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 16);
}

static int32_t num(const char *s)
{
    return (int32_t)strtol(s, NULL, 0);
}

// ------------------------------------------------------------ the names

#define MAX_NAMES 8192

static struct {
    const void *p;
    char        name[24];
} names[MAX_NAMES];
static int nnames;

static void name(const void *p, const char *s)
{
    if (nnames == MAX_NAMES) {
        fprintf(stderr, "too many names\n");
        exit(2);
    }
    names[nnames].p = p;
    snprintf(names[nnames].name, sizeof names[nnames].name, "%s", s);
    nnames++;
}

static void namef(const void *p, const char *fmt, int a, int b)
{
    char s[24];

    snprintf(s, sizeof s, fmt, a, b);
    name(p, s);
}

static const char *sym(const void *p)
{
    uintptr_t u = (uintptr_t)p;
    int       i;

    if (p == NULL)
        return "0";
    if (u == (uintptr_t)0xcdcdcdcdcdcdcdcdull || u == 0xcdcdcdcdu)
        return "cd";
    for (i = nnames - 1; i >= 0; i--)
        if (names[i].p == p)
            return names[i].name;
    return "?";
}

static void *ref(const char *s)
{
    int i;

    if (!strcmp(s, "0"))
        return NULL;
    for (i = nnames - 1; i >= 0; i--)
        if (!strcmp(names[i].name, s))
            return (void *)names[i].p;
    fprintf(stderr, "no such name %s\n", s);
    exit(2);
}

static int count_of(char prefix)
{
    static int counts[128];

    return counts[(unsigned char)prefix]++;
}

// --------------------------------------------------------- the blocks

static _Alignas(16) uint8_t heap[1 << 22];
static size_t heap_top;
static int    fill = 0xcd;

static void *block_fill(size_t size, int f)
{
    void *p;

    heap_top = (heap_top + 15) & ~(size_t)15;
    if (heap_top + size > sizeof heap) {
        fprintf(stderr, "heap exhausted\n");
        exit(2);
    }
    p = heap + heap_top;
    heap_top += size;
    memset(p, f, size);
    return p;
}

static void *block(size_t size)
{
    return block_fill(size, fill);
}

static void words(const void *p, int n)
{
    const uint8_t *b = p;
    int            i;

    for (i = 0; i < n; i++) {
        uint32_t w;

        memcpy(&w, b + 4 * i, 4);
        printf(" %08x", w);
    }
}

static void setw(void *dst, char **a, int n)
{
    uint8_t *d = dst;
    int      i;

    for (i = 0; i < n; i++) {
        uint32_t w = hex(a[i]);

        memcpy(d + 4 * i, &w, 4);
    }
}

// ---------------------------------------------------- the world it reads

RaceParameters        TheRaceParameters;
World                *pCurrentWorld;
int32_t               WorldTimer;
int32_t               WorldLoopCounter;
ScenerySectionHeader *ScenerySectionHeaderTable[SCENERY_MAX_SECTIONS];
CollisionStats        TheCollisionStats;
CollisionBodyNode     CollisionBodyList;
bVector3              ZeroVector;
bMatrix4              ZeroMatrix;
AcidEffectSystem      WorldEffects;
BSlotPool            *RigidBodySlotPool;

static _Alignas(16) uint8_t tok_vp[16], tok_sp[16], tok_rp[16], tok_xp[16];
static _Alignas(16) uint8_t tok_pp[16], tok_world[16], tok_cars[NCARS][16];

#define CBL_END ((CollisionBody *)(void *)&CollisionBodyList)

// The scripted answers, in order.
typedef struct { int32_t found; uint32_t e, n[3]; } ElevAnswer;
static ElevAnswer elevq[64];
static int        elevq_n, elevq_i;
static uint32_t   bvq[64][12], auxq[64][8], mvq[64][4], orthq[64][16];
static int        bvq_n, bvq_i, auxq_n, auxq_i, mvq_n, mvq_i, orthq_n, orthq_i;
static int32_t    idq[64];
static int        idq_n, idq_i;
static int32_t    nextid = 100;

static struct { char pool[8]; int32_t v; } fulls[16];
static int     nfulls;
static int32_t freeslots = 32;

static uint32_t noart[64], pipes[64];
static int      nnoart, npipes;
static char     cnull[64][24];
static int      ncnull;
static struct { char name[24]; uint32_t v; } dists[64];
static int      ndists;

static struct {
    char       body[24];
    int        i;
    Collision *c;
    void      *car1, *car2;
} cols[64];
static int ncols;

static struct { const void *o; uint32_t h; } wohashes[256];
static int nwohashes;

static Smokeable *creatorret;

// The scenery sections the script made.
static struct { ScenerySectionHeader *h; int ninst, ninfo; } sections[SCENERY_MAX_SECTIONS];

// The chunks the loader was handed.
static uint8_t *infochunks[16], *spchunks[16];
static int      ninfochunks, nspchunks, ninfo, nspawner;

#define MAX_PENDING 32
static char *pending[MAX_PENDING][24];
static int   npending;

static int in_set(const uint32_t *set, int n, uint32_t v)
{
    int i;

    for (i = 0; i < n; i++)
        if (set[i] == v)
            return 1;
    return 0;
}

static void set_remove(uint32_t *set, int *n, uint32_t v)
{
    int i;

    for (i = 0; i < *n; i++)
        if (set[i] == v) {
            set[i] = set[--*n];
            return;
        }
}

static const char *pool_name(const BSlotPool *p)
{
    return sym(p);
}

// ------------------------------------------------------- the list of bodies

static void cbl_insert(CollisionBody *b)
{
    CollisionBody *head = CollisionBodyList.next;

    CollisionBodyList.next = b;
    head->Link.prev = b;
    b->Link.next = head;
    b->Link.prev = CBL_END;
}

static void cbl_remove(CollisionBody *b)
{
    CollisionBody *nx = b->Link.next, *pv = b->Link.prev;

    pv->Link.next = nx;
    nx->Link.prev = pv;
}

static void body_common(CollisionBody *b, int32_t id, int32_t type,
                        int32_t dyn, uint32_t vt)
{
    b->Type = (int8_t)type;
    b->Dynamic = (int8_t)dyn;
    b->ID = (int16_t)id;
    b->NumWitnesses = 0;
    b->CollisionsDisabled = 7;
    b->NumCollisions = 0;
    b->ActiveCollisionDetection = 7;
    b->_vtable = vt;
    cbl_insert(b);
}

// ---------------------------------------------------------------- stubs

void topology_init(TopologyCoordinate *tc)
{
    printf("  tcinit %s\n", sym(tc));
}

void topology_destroy(TopologyCoordinate *tc)
{
    printf("  tcdtor %s\n", sym(tc));
}

float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    ElevAnswer a = { 1, 0x3f000000u, { 0, 0, 0x3f800000u } };

    if (elevq_i < elevq_n)
        a = elevq[elevq_i++];
    if (normal != NULL) {
        normal->x = bf(a.n[0]);
        normal->y = bf(a.n[1]);
        normal->z = bf(a.n[2]);
    }
    if (found != NULL)
        *found = a.found;
    printf("  elev %s", sym(tc));
    words(pt, 3);
    printf(" terr %s -> %d %08x %08x %08x %08x\n", sym(terrain), (int)a.found,
           a.e, a.n[0], a.n[1], a.n[2]);
    return bf(a.e);
}

void topology_set_interest_bbox3(TopologyCoordinate *tc, const bVector3 *pos,
                                 float r, const bVector3 *vel)
{
    printf("  interest %s %s", sym(tc), sym(pos));
    words(pos, 3);
    printf(" %08x %s", fb(r), sym(vel));
    words(vel, 3);
    printf("\n");
}

void topology_clear_interest_bbox(TopologyCoordinate *tc)
{
    printf("  uninterest %s\n", sym(tc));
}

int bIsSlotPoolFull(const BSlotPool *pool)
{
    int32_t v = 0;
    int     i;

    for (i = 0; i < nfulls; i++)
        if (!strcmp(fulls[i].pool, pool_name(pool)))
            v = fulls[i].v;
    printf("  full %s -> %d\n", pool_name(pool), (int)v);
    return v;
}

int bCountFreeSlots(const BSlotPool *pool)
{
    printf("  freeslots %s -> %d\n", pool_name(pool), (int)freeslots);
    return freeslots;
}

void *bSlotOMalloc(BSlotPool *pool)
{
    void *p;

    if (pool == (BSlotPool *)(void *)tok_vp) {
        p = block(sizeof(VirginSmokeable));
        namef(p, "V%d", count_of('V'), 0);
    } else if (pool == (BSlotPool *)(void *)tok_sp) {
        Smokeable *s = block(sizeof *s);
        int        k = count_of('S');

        p = s;
        namef(s, "S%d", k, 0);
        namef(&s->System, "S%d.sys", k, 0);
        namef(&s->TC, "S%d.tc", k, 0);
        namef(&s->TheWorldObject, "S%d.wo", k, 0);
        namef(&s->TheWorldObject.Matrix, "S%d.m", k, 0);
        namef(&s->AnchorEmitterList, "S%d.al", k, 0);
        namef(&s->DynamicEmitterList, "S%d.dl", k, 0);
    } else if (pool == (BSlotPool *)(void *)tok_rp) {
        RigidBody *rb = block(sizeof *rb);
        int        k = count_of('R');

        p = rb;
        namef(rb, "R%d", k, 0);
        namef(&rb->State.X, "R%d.X", k, 0);
        namef(&rb->State.R, "R%d.R", k, 0);
        namef(&rb->Velocity, "R%d.v", k, 0);
        namef(&rb->AngularVelocity, "R%d.w", k, 0);
        namef(&rb->I_body_inv, "R%d.ibi", k, 0);
    } else {
        p = block(64);
        namef(p, "B%d", count_of('B'), 0);
    }
    printf("  omalloc %s -> %s\n", pool_name(pool), sym(p));
    return p;
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    printf("  free %s %s\n", pool_name(pool), sym(slot));
}

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *pname,
                        int poolNum)
{
    int size = slotSize;

    if (slotSize == (int)sizeof(VirginSmokeable))
        size = 100;
    else if (slotSize == (int)sizeof(Smokeable))
        size = 1136;
    printf("  newpool %d %d %s %d\n", size, numSlots, pname, poolNum);
    if (!strcmp(pname, "VirginSmokeableSlotPool"))
        return (BSlotPool *)(void *)tok_vp;
    if (!strcmp(pname, "SmokeableSlotPool"))
        return (BSlotPool *)(void *)tok_sp;
    return (BSlotPool *)(void *)tok_xp;
}

void bDeleteSlotPool(BSlotPool *pool)
{
    printf("  delpool %s\n", pool_name(pool));
}

void *bMalloc(int size, const char *nm, int flags, int pool)
{
    void *p = block((size_t)size);

    (void)nm;
    (void)flags;
    namef(p, "M%d", count_of('M'), 0);
    printf("  bmalloc %d %d -> %s\n",
           size == (int)sizeof(RectPolyhedron) ? RETAIL_RECT_SIZE : size,
           pool, sym(p));
    return p;
}

int32_t collisionbody_get_next_id(void)
{
    int32_t v = idq_i < idq_n ? idq[idq_i++] : nextid++;

    printf("  nextid -> %d\n", (int)v);
    return v;
}

void collisionbody_set_debug_name(CollisionBody *b, const char *nm)
{
    printf("  name %s %s\n", sym(b), nm);
}

CollisionBody *collisionbody_find(int32_t id)
{
    CollisionBody *b, *r = NULL;

    for (b = CollisionBodyList.next; b != CBL_END; b = b->Link.next)
        if (b->ID == id) {
            r = b;
            break;
        }
    printf("  find %d -> %s\n", (int)id, sym(r));
    return r;
}

struct Collision *collisionbody_get_collision(CollisionBody *b, int32_t i)
{
    Collision *c = NULL;
    int        k;

    for (k = 0; k < ncols; k++)
        if (!strcmp(cols[k].body, sym(b)) && cols[k].i == i)
            c = cols[k].c;
    printf("  getcol %s %d -> %s\n", sym(b), (int)i, sym(c));
    return c;
}

void collisionbody_set_bbox_min_max(CollisionBody *b, const bVector2 *min,
                                    const bVector2 *max)
{
    printf("  bbox %s", sym(b));
    words(min, 2);
    words(max, 2);
    printf("\n");
}

void collisionbody_plot_to_caffeine(CollisionBody *b, const bMatrix4 *m,
                                    const bVector3 *p)
{
    printf("  caffeine %s", sym(b));
    words(m, 16);
    printf(" %s", sym(p));
    words(p, 3);
    printf("\n");
}

StaticCollisionBody *staticcollisionbody_init(StaticCollisionBody *s,
                                              int32_t id, int32_t type)
{
    printf("  sinit %s %d %d\n", sym(s), (int)id, (int)type);
    body_common(&s->Body, id, type, 0, STATICCOLLISIONBODY_VTABLE);
    return s;
}

void staticcollisionbody_destroy(StaticCollisionBody *s, int32_t flags)
{
    printf("  sdtor %s %d\n", sym(s), (int)flags);
    cbl_remove(&s->Body);
}

DynamicCollisionBody *dynamiccollisionbody_init(DynamicCollisionBody *d,
                                                int32_t id, int32_t type,
                                                TopologyCoordinate *tc)
{
    printf("  dinit %s %d %d %s\n", sym(d), (int)id, (int)type, sym(tc));
    body_common(&d->Body, id, type, 1, DYNAMICCOLLISIONBODY_VTABLE);
    d->PhysicsMode = 0;
    d->pTC = tc;
    d->pSystem = NULL;
    d->pBody = NULL;
    return d;
}

void dynamiccollisionbody_destroy(DynamicCollisionBody *d, int32_t flags)
{
    printf("  ddtor %s %d\n", sym(d), (int)flags);
    cbl_remove(&d->Body);
}

void dynamiccollisionbody_build_bounding_volumes(DynamicCollisionBody *d)
{
    static const float def[12] = { 0.5f, 1.5f, 0.75f, 1.25f, -0.5f, -0.5f,
                                   -0.25f, 0.0f, 0.5f, 0.5f, 1.75f, 0.0f };
    uint32_t v[12];
    int      i;

    if (bvq_i < bvq_n) {
        memcpy(v, bvq[bvq_i++], sizeof v);
    } else {
        for (i = 0; i < 12; i++)
            v[i] = fb(def[i]);
    }
    d->CylinderBaseHeight = bf(v[0]);
    d->CylinderTopHeight = bf(v[1]);
    d->CylinderRadius = bf(v[2]);
    d->Radius = bf(v[3]);
    memcpy(&d->LocalBBMin, v + 4, 16);
    memcpy(&d->LocalBBMax, v + 8, 16);
    printf("  buildbv %s\n", sym(d));
}

void dynamiccollisionbody_update_position(DynamicCollisionBody *d)
{
    printf("  updatepos %s\n", sym(d));
}

void dynamiccollisionbody_begin_move(DynamicCollisionBody *d, float t)
{
    printf("  beginmove %s %08x\n", sym(d), fb(t));
}

PhysicsSystem *physicssystem_init(PhysicsSystem *sys)
{
    printf("  psinit %s\n", sym(sys));
    sys->pNext = 0x11111111u;
    sys->pPrev = 0x22222222u;
    sys->Size = 0;
    sys->_vtable = PHYSICSSYSTEM_VTABLE;
    return sys;
}

void physicssystem_fini(PhysicsSystem *sys, int32_t flags)
{
    printf("  psfini %s %d\n", sym(sys), (int)flags);
}

void physicssystem_add_component(PhysicsSystem *sys, PhysicsComponent *c)
{
    printf("  addcomp %s %s\n", sym(sys), sym(c));
}

void physicssystem_integrate_euler(PhysicsSystem *sys, float dt)
{
    printf("  euler %s %08x\n", sym(sys), fb(dt));
}

void physicssystem_compute_auxiliaries(PhysicsSystem *sys)
{
    printf("  aux %s\n", sym(sys));
    if (auxq_i < auxq_n) {
        Smokeable *s = (Smokeable *)(void *)((char *)sys
                                             - offsetof(Smokeable, System));
        RigidBody *rb = s->Dynamic.pBody;

        memcpy(&rb->Velocity, auxq[auxq_i], 16);
        memcpy(&rb->AngularVelocity, auxq[auxq_i] + 4, 16);
        auxq_i++;
    }
}

RigidBody *rigidbody_init(RigidBody *rb, const RigidBodyInfo *rbi)
{
    int i;

    printf("  rbinit %s %s\n", sym(rb), sym(rbi));
    memset(&rb->State, 0, sizeof *rb - offsetof(RigidBody, State));
    rb->RBI = rbi;
    rb->Mass = rbi->Mass;
    rb->Mass_inv = rbi->Mass * 0.5f;
    for (i = 0; i < 16; i++)
        (&rb->I_body_inv.v0.x)[i] = 0.25f * (float)i - 1.0f;
    rb->MotionDamping = 0x77;
    return rb;
}

void rigidbody_calibrate(RigidBody *rb, const bVector4 *cog)
{
    printf("  rbcal %s %s\n", sym(rb), sym(cog));
}

void rigidbody_calculate_inertia_tensor(RigidBody *rb)
{
    printf("  rbinertia %s\n", sym(rb));
}

void rigidbody_set_state(RigidBody *rb, const bVector4 *x, const bMatrix4 *r,
                         const bVector4 *p, const bVector4 *l)
{
    printf("  rbstate %s", sym(rb));
    words(x, 4);
    words(r, 16);
    words(p, 4);
    words(l, 3);
    printf("\n");
    rb->State.X = *x;
    rb->State.R = *r;
    rb->State.P = *p;
    rb->State.L.x = l->x;
    rb->State.L.y = l->y;
    rb->State.L.z = l->z;
}

void rigidbody_apply_force(RigidBody *rb, const bVector4 *f,
                           const bVector4 *at)
{
    printf("  rbforce %s", sym(rb));
    words(f, 4);
    words(at, 3);
    printf("\n");
}

void rigidbody_apply_impulse(RigidBody *rb, const bVector4 *j,
                             const bVector4 *at)
{
    printf("  rbimpulse %s", sym(rb));
    words(j, 4);
    words(at, 4);
    printf("\n");
}

AcidEmitter *afx_copy_emitter(const AcidEmitter *src)
{
    AcidEmitter *c = NULL;
    int          i, null = 0;

    for (i = 0; i < ncnull; i++)
        if (!strcmp(cnull[i], sym(src)))
            null = 1;
    if (!null) {
        c = block(sizeof *c);
        namef(c, "C%d", count_of('C'), 0);
    }
    printf("  acopy %s -> %s\n", sym(src), sym(c));
    return c;
}

void afx_get_emitters(bNode *list, uint32_t h)
{
    int n = (int)(h & 3), k;

    for (k = 0; k < n; k++) {
        AcidEmitter *e = block(sizeof *e);
        bNode       *tail = list->prev;

        namef(e, "E%d", count_of('E'), 0);
        e->NameHash = h + (uint32_t)k;
        tail->next = &e->Node;
        list->prev = &e->Node;
        e->Node.prev = tail;
        e->Node.next = list;
    }
    printf("  agets %s %08x -> %d\n", sym(list), h, n);
}

void afx_delete_emitters(bNode *list)
{
    printf("  adelall %s\n", sym(list));
    list->next = list;
    list->prev = list;
}

void acid_system_add_auto_emitter(AcidEffectSystem *s, AcidEmitter *e)
{
    printf("  addauto %s %s\n", sym(s), sym(e));
}

void acid_system_remove_auto_emitter(AcidEffectSystem *s, AcidEmitter *e)
{
    printf("  remauto %s %s\n", sym(s), sym(e));
}

void acid_emitter_delete(AcidEmitter *e, int32_t flags)
{
    printf("  emdel %s %d\n", sym(e), (int)flags);
}

bPNode *bpnode_malloc(void)
{
    bPNode *p = block(sizeof *p);

    namef(p, "N%d", count_of('N'), 0);
    printf("  pmalloc -> %s\n", sym(p));
    return p;
}

void bpnode_free(void *p)
{
    printf("  pfree %s\n", sym(p));
}

WorldObject *worldobject_construct(WorldObject *o, uint32_t h,
                                   const bMatrix4 *m, int32_t light)
{
    if (nwohashes == 256) {
        fprintf(stderr, "too many world objects\n");
        exit(2);
    }
    wohashes[nwohashes].o = o;
    wohashes[nwohashes].h = h;
    nwohashes++;
    printf("  woctor %s %08x %s %d\n", sym(o), h, sym(m), (int)light);
    return o;
}

void worldobject_destruct(WorldObject *o, int32_t flags)
{
    printf("  wodtor %s %d\n", sym(o), (int)flags);
}

uint32_t worldobject_get_name_hash(WorldObject *o)
{
    uint32_t h = 0;
    int      i;

    for (i = 0; i < nwohashes; i++)
        if (wohashes[i].o == o)
            h = wohashes[i].h;
    printf("  wohash %s -> %08x\n", sym(o), h);
    return h;
}

int32_t worldobject_does_art_exist(uint32_t h)
{
    int32_t v = in_set(noart, nnoart, h) ? 0 : 1;

    printf("  art %08x -> %d\n", h, (int)v);
    return v;
}

PipelinePolyhedron *find_pipeline_polyhedron(uint32_t h, bVector3 *cog)
{
    PipelinePolyhedron *r = in_set(pipes, npipes, h)
                            ? (PipelinePolyhedron *)(void *)tok_pp : NULL;

    printf("  pipe %08x %s -> %s\n", h, sym(cog), sym(r));
    return r;
}

RectPolyhedron *rectpoly_init(RectPolyhedron *r, float xmax, float xmin,
                              float ymax, float ymin, float zmax, float zmin)
{
    printf("  rect %s %08x %08x %08x %08x %08x %08x\n", sym(r), fb(xmax),
           fb(xmin), fb(ymax), fb(ymin), fb(zmax), fb(zmin));
    return r;
}

void vcpoly_destroy(VCPolyhedron *p, int32_t flags)
{
    printf("  vcdtor %s %d\n", sym(p), (int)flags);
}

int32_t terrain_match_hash(uint32_t h)
{
    int32_t v = (int32_t)((h >> 4) % 9u) - 1;

    printf("  terrain %08x -> %d\n", h, (int)v);
    return v;
}

float world_get_distance_to_closest_player(const World *w, const bVector3 *p)
{
    uint32_t v = 0x42c80000u;
    int      i;

    for (i = 0; i < ndists; i++)
        if (!strcmp(dists[i].name, sym(p)))
            v = dists[i].v;
    printf("  dist %s %s -> %08x\n", sym(w), sym(p), v);
    return bf(v);
}

void collision_get_colliding_cars(Collision *c, struct Car **car1,
                                  struct Car **car2)
{
    void *a = NULL, *b = NULL;
    int   k;

    for (k = 0; k < ncols; k++)
        if (c != NULL && cols[k].c == c) {
            a = cols[k].car1;
            b = cols[k].car2;
        }
    *car1 = a;
    *car2 = b;
    printf("  cars %s -> %s %s\n", sym(c), sym(a), sym(b));
}

void collision_sound_play_smokeable(const bVector3 *pos,
                                    struct SmokeableInfo *info)
{
    printf("  sound");
    words(pos, 3);
    printf(" %s\n", sym(info));
}

float bSinBam(uint16_t a)
{
    printf("  sin %d\n", (int)a);
    return (float)a / 65536.0f;
}

float bCosBam(uint16_t a)
{
    printf("  cos %d\n", (int)a);
    return (float)(65536 - (int)a) / 65536.0f;
}

void bIdentity(bMatrix4 *m)
{
    int i;

    printf("  identity %s\n", sym(m));
    for (i = 0; i < 16; i++)
        (&m->v0.x)[i] = i % 5 == 0 ? 1.0f : 0.0f;
}

void bMulMatrixVec3(bVector3 *o, const bMatrix4 *m, const bVector3 *v)
{
    uint32_t r[4];

    if (mvq_i < mvq_n) {
        memcpy(r, mvq[mvq_i++], 16);
    } else {
        memcpy(r, v, 12);
        r[3] = 0x3f800000u;
    }
    printf("  mulvec %s", sym(m));
    words(m, 16);
    printf(" %s", sym(v));
    words(v, 3);
    printf(" -> %08x %08x %08x %08x\n", r[0], r[1], r[2], r[3]);
    memcpy(o, r, 16);
}

void eOrthonormalizeMatrix(bMatrix4 *o, const bMatrix4 *m)
{
    uint32_t r[16];

    printf("  ortho %s", sym(m));
    words(m, 12);
    printf("\n");
    if (orthq_i < orthq_n) {
        memcpy(r, orthq[orthq_i++], 64);
    } else {
        memcpy(r, m, 48);
        r[12] = r[13] = r[14] = 0;
        r[15] = 0x3f800000u;
    }
    memcpy(o, r, 64);
}

static Smokeable *stub_creator(int32_t id, SmokeableInfo *info, uint32_t h)
{
    printf("  creator %d %s %08x -> %s\n", (int)id, sym(info), h,
           sym(creatorret));
    return creatorret;
}

// A table's OnLifetimeEnd, logged (vtlife): the smokeable's table copied
// under an address of its own.
#define LIFE_VTABLE 0x00400010u

static VtEntry life_vt[SMOKEABLE_VT_ENTRIES];

static void stub_life_end(void *self)
{
    printf("  lifeend %s\n", sym(self));
}

// -------------------------------------- the tables' other methods, unused

#define DUMMY(n) printf("  dummy %s\n", n)

void dynamiccollisionbody_set_position(CollisionBody *b, bVector3 *p)
{ (void)b; (void)p; DUMMY("dyn set_position"); }
float dynamiccollisionbody_get_max_backup_time(CollisionBody *b)
{ (void)b; DUMMY("dyn get_max_backup_time"); return 0.0f; }
#ifndef SMOKEABLE_TEST_EXTRA
void dynamiccollisionbody_backup(CollisionBody *b, float t)
{ (void)b; (void)t; DUMMY("dyn backup"); }
#endif
void dynamiccollisionbody_interpolate(CollisionBody *b, bVector3 *pos,
                                      bMatrix4 *rot, float t)
{ (void)b; (void)pos; (void)rot; (void)t; DUMMY("dyn interpolate"); }
void dynamiccollisionbody_recompute_auxilliaries(CollisionBody *b)
{ (void)b; DUMMY("dyn recompute_auxilliaries"); }
void dynamiccollisionbody_get_current_velocities(CollisionBody *b,
                                                 bVector3 *v, bVector3 *w)
{ (void)b; (void)v; (void)w; DUMMY("dyn get_current_velocities"); }
void dynamiccollisionbody_get_test_impulse_velocities(CollisionBody *b,
                                                      bVector3 *v,
                                                      bVector3 *w,
                                                      bVector3 *j,
                                                      bVector3 *at)
{
    (void)b; (void)v; (void)w; (void)j; (void)at;
    DUMMY("dyn get_test_impulse_velocities");
}
void dynamiccollisionbody_set_to_physics_mode(CollisionBody *b,
                                              CollisionBody *other)
{ (void)b; (void)other; DUMMY("dyn set_to_physics_mode"); }
float dynamiccollisionbody_change_in_energy(CollisionBody *b, bVector3 *j,
                                            bVector3 *at)
{ (void)b; (void)j; (void)at; DUMMY("dyn change_in_energy"); return 0.0f; }
void physicssystem_resolve_forces(PhysicsSystem *sys)
{ (void)sys; DUMMY("ps resolve_forces"); }

bVector3 *staticcollisionbody_get_velocity(CollisionBody *b)
{ (void)b; DUMMY("st get_velocity"); return NULL; }
bMatrix4 *staticcollisionbody_get_rotation(CollisionBody *b)
{ (void)b; DUMMY("st get_rotation"); return NULL; }
void staticcollisionbody_set_position(CollisionBody *b, bVector3 *p)
{ (void)b; (void)p; DUMMY("st set_position"); }
float staticcollisionbody_get_max_backup_time(CollisionBody *b)
{ (void)b; DUMMY("st get_max_backup_time"); return 0.0f; }
void staticcollisionbody_move(CollisionBody *b, float t)
{ (void)b; (void)t; DUMMY("st move"); }
void staticcollisionbody_backup(CollisionBody *b, float t)
{ (void)b; (void)t; DUMMY("st backup"); }
void staticcollisionbody_interpolate(CollisionBody *b, bVector3 *pos,
                                     bMatrix4 *rot, float t)
{ (void)b; (void)pos; (void)rot; (void)t; DUMMY("st interpolate"); }
void staticcollisionbody_recompute_auxilliaries(CollisionBody *b)
{ (void)b; DUMMY("st recompute_auxilliaries"); }
void staticcollisionbody_get_current_velocities(CollisionBody *b,
                                                bVector3 *v, bVector3 *w)
{ (void)b; (void)v; (void)w; DUMMY("st get_current_velocities"); }
void staticcollisionbody_get_test_impulse_velocities(CollisionBody *b,
                                                     bVector3 *v,
                                                     bVector3 *w,
                                                     bVector3 *a,
                                                     bVector3 *c)
{
    (void)b; (void)v; (void)w; (void)a; (void)c;
    DUMMY("st get_test_impulse_velocities");
}
void staticcollisionbody_set_to_physics_mode(CollisionBody *b,
                                             CollisionBody *other)
{ (void)b; (void)other; DUMMY("st set_to_physics_mode"); }
float staticcollisionbody_consider_impulse(CollisionBody *b, bVector3 *point,
                                           bVector3 *impulse)
{ (void)b; (void)point; (void)impulse; DUMMY("st consider_impulse");
  return 0.0f; }
void staticcollisionbody_apply_impulse(CollisionBody *b, bVector3 *point,
                                       bVector3 *impulse)
{ (void)b; (void)point; (void)impulse; DUMMY("st apply_impulse"); }
int32_t staticcollisionbody_are_collisions_enabled(CollisionBody *b)
{ (void)b; DUMMY("st are_collisions_enabled"); return 0; }
float staticcollisionbody_get_mass_inverse(CollisionBody *b)
{ (void)b; DUMMY("st get_mass_inverse"); return 0.0f; }
bMatrix4 *staticcollisionbody_get_inertia_tensor_inverse(CollisionBody *b)
{ (void)b; DUMMY("st get_inertia_tensor_inverse"); return NULL; }
int32_t staticcollisionbody_is_moveable(CollisionBody *b)
{ (void)b; DUMMY("st is_moveable"); return 0; }
float staticcollisionbody_change_in_energy(CollisionBody *b, bVector3 *point,
                                           bVector3 *impulse)
{ (void)b; (void)point; (void)impulse; DUMMY("st change_in_energy");
  return 0.0f; }
float staticcollisionbody_get_bounciness(CollisionBody *b)
{ (void)b; DUMMY("st get_bounciness"); return 0.0f; }
float staticcollisionbody_get_friction(CollisionBody *b)
{ (void)b; DUMMY("st get_friction"); return 0.0f; }
int32_t collisionbody_is_blinking(CollisionBody *b)
{ (void)b; DUMMY("cb is_blinking"); return 0; }

// The replay's DoSnapshots, slot 16 of the two tables (smokesnap.c, TASKS
// 72d-2, checked by tools/worldsnap_check.py): named in the tables' dumps,
// never called here.
static void snapshot_unreached(const char *f)
{
    fprintf(stderr, "%s reached\n", f);
    exit(3);
}

void smokeable_do_snapshot(CollisionBody *b, struct ReplaySnapshot *s)
{ (void)b; (void)s; snapshot_unreached("smokeable_do_snapshot"); }
void virginsmokeable_do_snapshot(CollisionBody *b, struct ReplaySnapshot *s)
{ (void)b; (void)s; snapshot_unreached("virginsmokeable_do_snapshot"); }

// The tables' functions by the names the model gives retail's.
static const struct {
    VtFn        fn;
    const char *name;
} fnames[] = {
#define FN(f) { (VtFn)(f), #f }
    FN(smokeable_get_position), FN(smokeable_get_velocity),
    FN(smokeable_get_rotation), FN(smokeable_move),
    FN(smokeable_consider_impulse), FN(smokeable_apply_impulse),
    FN(smokeable_are_collisions_enabled), FN(smokeable_get_terrain_type),
    FN(smokeable_get_mass_inverse), FN(smokeable_get_inertia_tensor_inverse),
    FN(smokeable_is_moveable), FN(smokeable_is_blinking),
    FN(smokeable_get_bounciness), FN(smokeable_get_friction),
    FN(smokeable_get_smoke_type), FN(smokeable_on_lifetime_end),
    FN(virginsmokeable_get_position), FN(virginsmokeable_get_terrain_type),
    FN(dynamiccollisionbody_set_position),
    FN(dynamiccollisionbody_get_max_backup_time),
    FN(dynamiccollisionbody_backup), FN(dynamiccollisionbody_interpolate),
    FN(dynamiccollisionbody_recompute_auxilliaries),
    FN(dynamiccollisionbody_get_current_velocities),
    FN(dynamiccollisionbody_get_test_impulse_velocities),
    FN(dynamiccollisionbody_set_to_physics_mode),
    FN(dynamiccollisionbody_change_in_energy),
    FN(physicssystem_resolve_forces),
    FN(staticcollisionbody_get_velocity), FN(staticcollisionbody_get_rotation),
    FN(staticcollisionbody_set_position),
    FN(staticcollisionbody_get_max_backup_time),
    FN(staticcollisionbody_move), FN(staticcollisionbody_backup),
    FN(staticcollisionbody_interpolate),
    FN(staticcollisionbody_recompute_auxilliaries),
    FN(staticcollisionbody_get_current_velocities),
    FN(staticcollisionbody_get_test_impulse_velocities),
    FN(staticcollisionbody_set_to_physics_mode),
    FN(staticcollisionbody_consider_impulse),
    FN(staticcollisionbody_apply_impulse),
    FN(staticcollisionbody_are_collisions_enabled),
    FN(staticcollisionbody_get_mass_inverse),
    FN(staticcollisionbody_get_inertia_tensor_inverse),
    FN(staticcollisionbody_is_moveable),
    FN(staticcollisionbody_change_in_energy),
    FN(staticcollisionbody_get_bounciness),
    FN(staticcollisionbody_get_friction), FN(collisionbody_is_blinking),
    FN(smokeable_do_snapshot), FN(virginsmokeable_do_snapshot),
#undef FN
};

static const char *fn_name(VtFn fn)
{
    size_t i;

    if (fn == NULL)
        return "-";
    for (i = 0; i < sizeof fnames / sizeof fnames[0]; i++)
        if (fnames[i].fn == fn)
            return fnames[i].name;
    return "local";
}

// --------------------------------------------------------------- dumps

static void body_fields(const CollisionBody *b)
{
    printf("next %s prev %s poly %s type %d dyn %d id %d wit %d dis %d "
           "ncol %d acd %d bb", sym(b->Link.next), sym(b->Link.prev),
           sym(b->pPoly), (int)b->Type, (int)b->Dynamic, (int)b->ID,
           (int)b->NumWitnesses, (int)b->CollisionsDisabled,
           (int)b->NumCollisions, (int)b->ActiveCollisionDetection);
    words(&b->BBoxMin, 2);
    words(&b->BBoxMax, 2);
    printf(" vt %08x", b->_vtable);
}

static void plist(const bNode *lst)
{
    const bNode *n;
    int          i = 0;

    for (n = lst->next; n != lst && i < 64; n = n->next, i++)
        printf(" %s:%s<%s", sym(n), sym(((const bPNode *)(const void *)n)->Object),
               sym(n->prev));
    printf(" | %s<%s", sym(lst->next), sym(lst->prev));
}

static void tlist(const bNode *lst)
{
    const bNode *n;
    int          i = 0;

    for (n = lst->next; n != lst && i < 64; n = n->next, i++)
        printf(" %s<%s", sym(n), sym(n->prev));
    printf(" | %s<%s", sym(lst->next), sym(lst->prev));
}

static void dump_smokeable(const Smokeable *s)
{
    const DynamicCollisionBody *d = &s->Dynamic;

    printf("smk %s ", sym(s));
    body_fields(&d->Body);
    printf(" mode %d tc %s sys %s body %s bt %08x brot", (int)d->PhysicsMode,
           sym(d->pTC), sym(d->pSystem), sym(d->pBody), fb(d->BackupTime));
    words(&d->BackupRotation, 16);
    printf(" bpos");
    words(&d->BackupPosition, 4);
    printf(" bvel");
    words(&d->BackupVelocity, 3);
    printf(" cyl");
    words(&d->CylinderBaseHeight, 4);
    printf(" lbb");
    words(&d->LocalBBMin, 4);
    words(&d->LocalBBMax, 4);
    printf(" ps %08x %08x %d %08x si %s as %08x bs %08x t %08x %08x %08x "
           "sp %s gr %08x en %08x wm", s->System.pNext, s->System.pPrev,
           (int)s->System.Size, s->System._vtable, sym(s->SI),
           fb(s->AnchorStrength), fb(s->BreakingStrength),
           s->TimeCreated.PackedTime, s->TimeAwoken.PackedTime,
           s->TimeLastCarContact.PackedTime, sym(s->pSmokeableSpawner),
           fb(s->GroundRaise), (uint32_t)s->TheWorldObject.Enabled);
    words(&s->TheWorldObject.Matrix, 16);
    printf(" al");
    plist(&s->AnchorEmitterList);
    printf(" dl");
    plist(&s->DynamicEmitterList);
    printf(" aa %d da %d awake %d blink %d\n", (int)s->AnchorEmittersAdded,
           (int)s->DynamicEmittersAdded, (int)s->Awake, (int)s->Blinking);
}

static void dump_virgin(const VirginSmokeable *v)
{
    printf("vir %s ", sym(v));
    body_fields(&v->Static.Body);
    printf(" sp %s si %s inst %s info %s\n", sym(v->pSmokeableSpawner),
           sym(v->pSmokeableInfo), sym(v->pSceneryInstance),
           sym(v->pSceneryInfo));
}

static void dump_rb(const RigidBody *rb, int w)
{
    printf("rb %s rbi %s X", sym(rb), sym(rb->RBI));
    words(&rb->State.X, 4);
    printf(" R");
    words(&rb->State.R, 16);
    printf(" P");
    words(&rb->State.P, 3);
    printf(" L");
    words(&rb->State.L, 3);
    printf(" v");
    words(&rb->Velocity, 4);
    printf(" w");
    words(&rb->AngularVelocity, 4);
    printf(" md %d mass %08x minv %08x ibi", (int)rb->MotionDamping,
           fb(rb->Mass), fb(rb->Mass_inv));
    words(&rb->I_body_inv, 16);
    if (w)
        printf(" pw %08x lw %08x", fb(rb->State.P.w), fb(rb->State.L.w));
    printf("\n");
}

static void dump_emitter(const AcidEmitter *c)
{
    printf("em %s state %d lw", sym(c), (int)c->State);
    words(&c->LocalWorld, 16);
    printf(" iv");
    words(&c->InheritVelocity, 4);
    printf("\n");
}

static void dump_cbl(void)
{
    const CollisionBody *b;
    int                  i = 0;

    printf("cbl");
    for (b = CollisionBodyList.next; b != CBL_END && i < 200;
         b = b->Link.next, i++)
        printf(" %s<%s", sym(b), sym(b->Link.prev));
    printf(" | %s<%s\n", sym(CollisionBodyList.next),
           sym(CollisionBodyList.prev));
}

static void dump_stats(void)
{
    const CollisionStats *cs = &TheCollisionStats;

    printf("stats %d %d %d %d awake %d vp %s sp %s spawners %s %d\n",
           (int)cs->NumVirginSmokeableCollisionBodies,
           (int)cs->NumSmokeableCollisionBodies,
           (int)cs->HighestNumVirginSmokeableCollisionBodies,
           (int)cs->HighestNumSmokeableCollisionBodies,
           (int)AwakeSmokeablesCount, sym(VirginSmokeableSlotPool),
           sym(SmokeableSlotPool), sym(pSmokeableSpawners),
           (int)NumSmokeableSpawners);
}

static void dump_infos(void)
{
    const bNode *n;
    int          i = 0;

    for (n = SmokeableInfoList.next; n != &SmokeableInfoList && i < 64;
         n = n->next, i++) {
        const SmokeableInfo *si = (const SmokeableInfo *)(const void *)n;

        printf("info %s<%s ch %s %s %s %s terr %d al", sym(n), sym(n->prev),
               sym(si->pChildren[0]), sym(si->pChildren[1]),
               sym(si->pChildren[2]), sym(si->pChildren[3]),
               (int)si->TheTerrainType);
        tlist(&si->AnchorEmitterList);
        printf(" dl");
        tlist(&si->DynamicEmitterList);
        printf("\n");
    }
    printf("sil %s<%s\n", sym(SmokeableInfoList.next),
           sym(SmokeableInfoList.prev));
}

static void dump_section(int s)
{
    int i, k;

    for (i = 0; i < sections[s].ninst; i++) {
        const SceneryInstance *p = &sections[s].h->pSceneryInstance[i];

        printf("inst %s excl %04x rot", sym(p), p->ExcludeFlags);
        for (k = 0; k < 9; k++)
            printf(" %d", (int)p->Rotation[k]);
        printf(" pos");
        words(p->Position, 3);
        printf("\n");
    }
}

static void dump_vt(void)
{
    static const struct { const char *tag; uint32_t image; } t[] = {
        { "smk", SMOKEABLE_VTABLE },
        { "sys", SMOKEABLE_SYSTEM_VTABLE },
        { "vir", VIRGINSMOKEABLE_VTABLE },
    };
    int k, i, n;

    for (k = 0; k < 3; k++) {
        const VtEntry *e = vt_table(t[k].image, &n);

        printf("vt %s", t[k].tag);
        for (i = 0; i < n; i++)
            printf(" %d:%d:%s", 8 * i,
                   e[i].delta == -(int)offsetof(Smokeable, System)
                   ? -RETAIL_SYSTEM_OFFSET : (int)e[i].delta,
                   fn_name(e[i].fn));
        printf("\n");
    }
}

static void dump_creators(void)
{
    int k;

    printf("creators");
    for (k = 0; k < ST_NUM_SMOKEABLE_TYPES; k++) {
        SmokeableCreatorFn f = SmokeableCreators[k];

        printf(" %s", f == NULL ? "0" : f == smokeable_basic_creator ? "basic"
                      : f == stub_creator ? "stub" : "?");
    }
    printf("\n");
}

// ---------------------------------------------------------- the chunks

static void info_record(SmokeableInfo *si, char **a)
{
    int k;

    snprintf(si->Name, sizeof si->Name, "%s", a[0]);
    si->RBI.Mass = bf(hex(a[20]));
    si->NameHash = hex(a[1]);
    si->AnchorEmitterGroupNameHash = hex(a[2]);
    si->DynamicEmitterGroupNameHash = hex(a[3]);
    si->NumChildren = num(a[4]);
    for (k = 0; k < 4; k++)
        si->ChildNameHashes[k] = hex(a[5 + k]);
    for (k = 0; k < 3; k++)
        si->CenterOfMass[k] = bf(hex(a[9 + k]));
    si->Padding = bf(hex(a[12]));
    si->Lifetime = bf(hex(a[13]));
    si->AnchorStrength = bf(hex(a[14]));
    si->BreakingStrength = bf(hex(a[15]));
    si->Bounciness = bf(hex(a[16]));
    si->TerrainTypeHash = hex(a[17]);
    si->Friction = bf(hex(a[18]));
    setw(&si->Padding2, a + 19, 1);
}

static void put32(uint8_t *p, uint32_t v)
{
    memcpy(p, &v, 4);
}

static void load_infos(void)
{
    int      n = npending, i, r;
    uint8_t *c = block_fill(16 + sizeof(SmokeableInfo) * (size_t)n, 0);

    put32(c, 0x00034026u);
    put32(c + 4, (uint32_t)(8 + sizeof(SmokeableInfo) * (size_t)n));
    for (i = 0; i < n; i++) {
        SmokeableInfo *si = (SmokeableInfo *)(void *)(c + 16
                                                      + sizeof *si * (size_t)i);
        int k = ninfo++;

        namef(si, "I%d", k, 0);
        namef(&si->RBI, "I%d.rbi", k, 0);
        namef(si->CenterOfMass, "I%d.com", k, 0);
        namef(&si->DynamicEmitterList, "I%d.dl", k, 0);
        namef(&si->AnchorEmitterList, "I%d.al", k, 0);
        info_record(si, pending[i]);
    }
    for (i = 0; i < n; i++) {
        int k;

        for (k = 0; k < 24; k++)
            free(pending[i][k]);
    }
    npending = 0;
    infochunks[ninfochunks++] = c;
    r = smokeable_loader(c);
    printf("load %d -> %d\n", n, r);
}

static void load_spawners(char **a, int n)
{
    uint8_t *c = block_fill(8 + 8 * (size_t)n, 0);
    int      i, r;

    put32(c, 0x00034027u);
    put32(c + 4, (uint32_t)(8 * n));
    for (i = 0; i < n; i++) {
        SmokeableSpawner *p = (SmokeableSpawner *)(void *)(c + 8 + 8 * i);
        char             *s = a[i], *t;

        namef(p, "P%d", nspawner++, 0);
        p->SmokeableInfoHash = (uint32_t)strtoul(s, &t, 16);
        p->ScenerySectionNumber = (int16_t)strtol(t + 1, &t, 0);
        p->SceneryInstanceNumber = (int16_t)strtol(t + 1, &t, 0);
    }
    spchunks[nspchunks++] = c;
    r = smokeable_loader(c);
    printf("spawners %d -> %d\n", n, r);
}

// ----------------------------------------------------------------- ops

static void smokeable_field(Smokeable *s, const char *f, char **v)
{
    if (!strcmp(f, "wit"))
        s->Dynamic.Body.NumWitnesses = (int8_t)num(v[0]);
    else if (!strcmp(f, "dis"))
        s->Dynamic.Body.CollisionsDisabled = (int8_t)num(v[0]);
    else if (!strcmp(f, "ncol"))
        s->Dynamic.Body.NumCollisions = (int8_t)num(v[0]);
    else if (!strcmp(f, "acd"))
        s->Dynamic.Body.ActiveCollisionDetection = (int8_t)num(v[0]);
    else if (!strcmp(f, "aa"))
        s->AnchorEmittersAdded = (int8_t)num(v[0]);
    else if (!strcmp(f, "da"))
        s->DynamicEmittersAdded = (int8_t)num(v[0]);
    else if (!strcmp(f, "awake"))
        s->Awake = (int8_t)num(v[0]);
    else if (!strcmp(f, "blink"))
        s->Blinking = (int8_t)num(v[0]);
    else if (!strcmp(f, "as"))
        s->AnchorStrength = bf(hex(v[0]));
    else if (!strcmp(f, "bs"))
        s->BreakingStrength = bf(hex(v[0]));
    else if (!strcmp(f, "tcr"))
        s->TimeCreated.PackedTime = hex(v[0]);
    else if (!strcmp(f, "taw"))
        s->TimeAwoken.PackedTime = hex(v[0]);
    else if (!strcmp(f, "tlc"))
        s->TimeLastCarContact.PackedTime = hex(v[0]);
    else if (!strcmp(f, "gr"))
        s->GroundRaise = bf(hex(v[0]));
    else if (!strcmp(f, "en"))
        s->TheWorldObject.Enabled = (int32_t)hex(v[0]);
    else if (!strcmp(f, "sp"))
        s->pSmokeableSpawner = ref(v[0]);
    else if (!strcmp(f, "si"))
        s->SI = ref(v[0]);
    else {
        fprintf(stderr, "smokeable field %s\n", f);
        exit(2);
    }
}

static void rb_field(RigidBody *rb, const char *f, char **v)
{
    if (!strcmp(f, "X"))
        setw(&rb->State.X, v, 4);
    else if (!strcmp(f, "R"))
        setw(&rb->State.R, v, 16);
    else if (!strcmp(f, "P"))
        setw(&rb->State.P, v, 4);
    else if (!strcmp(f, "L"))
        setw(&rb->State.L, v, 4);
    else if (!strcmp(f, "v"))
        setw(&rb->Velocity, v, 4);
    else if (!strcmp(f, "w"))
        setw(&rb->AngularVelocity, v, 4);
    else if (!strcmp(f, "mass"))
        setw(&rb->Mass, v, 1);
    else if (!strcmp(f, "minv"))
        setw(&rb->Mass_inv, v, 1);
    else {
        fprintf(stderr, "rigid body field %s\n", f);
        exit(2);
    }
}

typedef void      (*DelFn)(void *self, int32_t flags);
typedef void      (*VoidFn)(void *self);
typedef void      (*MoveFn)(void *self, float dt);
typedef float     (*ImpulseFn)(void *self, bVector3 *j, bVector3 *at);
typedef void      (*ApplyFn)(void *self, bVector3 *j, bVector3 *at);
typedef void     *(*PtrFn)(void *self);
typedef int32_t   (*IntFn)(void *self);
typedef float     (*FloatFn)(void *self);

static const VtEntry *body_slot(void *b, int slot)
{
    return vt_slot(((CollisionBody *)b)->_vtable, slot);
}

// A harness that includes this one (munition_test.c) defines
// SMOKEABLE_TEST_EXTRA and these two: its own ops, tried first, and what
// it sets up after the tables.
#ifdef SMOKEABLE_TEST_EXTRA
static int  extra_op(char **a, int na);
static void extra_init(void);
#endif

static void op(char **a, int na)
{
    const char *o = a[0];
    static _Alignas(16) bVector3 v1, v2;
    static _Alignas(16) bMatrix4 mx;

#ifdef SMOKEABLE_TEST_EXTRA
    if (extra_op(a, na))
        return;
#endif
    if (!strcmp(o, "info")) {
        int k;

        if (npending == MAX_PENDING) {
            fprintf(stderr, "too many pending infos\n");
            exit(2);
        }
        for (k = 0; k < 24; k++) {
            const char *s = k + 1 < na ? a[k + 1] : "0";

            pending[npending][k] = malloc(strlen(s) + 1);
            strcpy(pending[npending][k], s);
        }
        npending++;
    } else if (!strcmp(o, "load")) {
        load_infos();
    } else if (!strcmp(o, "loadbad")) {
        uint8_t *c = block_fill(16, 0);
        int      r, r2;

        put32(c, hex(a[1]));
        r = smokeable_loader(c);
        r2 = smokeable_unloader(c);
        printf("loadbad %s -> %d %d\n", a[1], r, r2);
    } else if (!strcmp(o, "unload")) {
        int r = smokeable_unloader(infochunks[num(a[1])]);

        printf("unload %s -> %d\n", a[1], r);
    } else if (!strcmp(o, "spawners")) {
        load_spawners(a + 1, na - 1);
    } else if (!strcmp(o, "unsp")) {
        int r = smokeable_unloader(spchunks[num(a[1])]);

        printf("unsp %s -> %d\n", a[1], r);
    } else if (!strcmp(o, "find")) {
        printf("find %s -> %s\n", a[1], sym(find_smokeable_info(hex(a[1]))));
    } else if (!strcmp(o, "spawner")) {
        printf("spawner %s -> %s\n", a[1], sym(smokeable_get_spawner(num(a[1]))));
    } else if (!strcmp(o, "spidx")) {
        printf("spidx %s -> %d\n", a[1],
               (int)smokeable_get_spawner_index(ref(a[1])));
    } else if (!strcmp(o, "sect")) {
        int s = num(a[1]), ninst = num(a[2]), ninf = num(a[3]), i;
        ScenerySectionHeader *h = block_fill(sizeof *h, 0);
        SceneryInstance      *inst = block_fill(sizeof *inst * (size_t)ninst, 0);
        SceneryInfo          *inf = block_fill(sizeof *inf * (size_t)ninf, 0);

        namef(h, "H%d", s, 0);
        for (i = 0; i < ninst; i++) {
            namef(&inst[i], "H%d.i%d", s, i);
            namef(inst[i].Position, "H%d.i%d.p", s, i);
        }
        for (i = 0; i < ninf; i++)
            namef(&inf[i], "H%d.f%d", s, i);
        h->pSceneryInfo = inf;
        h->pSceneryInstance = inst;
        ScenerySectionHeaderTable[s] = h;
        sections[s].h = h;
        sections[s].ninst = ninst;
        sections[s].ninfo = ninf;
    } else if (!strcmp(o, "inst")) {
        SceneryInstance *p =
            &sections[num(a[1])].h->pSceneryInstance[num(a[2])];
        int k;

        for (k = 0; k < 3; k++) {
            p->BBox.BBoxMin[k] = (int16_t)num(a[3 + k]);
            p->BBox.BBoxMax[k] = (int16_t)num(a[6 + k]);
        }
        p->SceneryInfoNumber = (int16_t)num(a[9]);
        p->ExcludeFlags = (uint16_t)num(a[10]);
        setw(p->Position, a + 11, 3);
        for (k = 0; k < 9; k++)
            p->Rotation[k] = (int16_t)num(a[14 + k]);
    } else if (!strcmp(o, "sinfo")) {
        sections[num(a[1])].h->pSceneryInfo[num(a[2])].NameHash[0] = hex(a[3]);
    } else if (!strcmp(o, "unsect")) {
        ScenerySectionHeaderTable[num(a[1])] = NULL;
    } else if (!strcmp(o, "secdump")) {
        dump_section(num(a[1]));
    } else if (!strcmp(o, "other")) {
        CollisionBody *b = block(sizeof *b);

        namef(b, "O%d", count_of('O'), 0);
        body_common(b, num(a[2]), num(a[1]), 0, 0);
    } else if (!strcmp(o, "rp")) {
        TheRaceParameters.NumPlayerCars = num(a[1]);
    } else if (!strcmp(o, "timer")) {
        WorldTimer = (int32_t)hex(a[1]);
    } else if (!strcmp(o, "loop")) {
        WorldLoopCounter = num(a[1]);
    } else if (!strcmp(o, "full")) {
        snprintf(fulls[nfulls].pool, sizeof fulls[nfulls].pool, "%s", a[1]);
        fulls[nfulls++].v = num(a[2]);
    } else if (!strcmp(o, "freeslots")) {
        freeslots = num(a[1]);
    } else if (!strcmp(o, "ids")) {
        int i;

        for (i = 1; i < na; i++)
            idq[idq_n++] = num(a[i]);
    } else if (!strcmp(o, "elev")) {
        elevq[elevq_n].found = num(a[1]);
        elevq[elevq_n].e = hex(a[2]);
        elevq[elevq_n].n[0] = hex(a[3]);
        elevq[elevq_n].n[1] = hex(a[4]);
        elevq[elevq_n].n[2] = hex(a[5]);
        elevq_n++;
    } else if (!strcmp(o, "bv")) {
        setw(bvq[bvq_n++], a + 1, 12);
    } else if (!strcmp(o, "aux")) {
        setw(auxq[auxq_n++], a + 1, 8);
    } else if (!strcmp(o, "mv")) {
        setw(mvq[mvq_n++], a + 1, 4);
    } else if (!strcmp(o, "orth")) {
        setw(orthq[orthq_n++], a + 1, 16);
    } else if (!strcmp(o, "noart")) {
        noart[nnoart++] = hex(a[1]);
    } else if (!strcmp(o, "art")) {
        set_remove(noart, &nnoart, hex(a[1]));
    } else if (!strcmp(o, "pipe")) {
        pipes[npipes++] = hex(a[1]);
    } else if (!strcmp(o, "nopipe")) {
        set_remove(pipes, &npipes, hex(a[1]));
    } else if (!strcmp(o, "cnull")) {
        snprintf(cnull[ncnull++], sizeof cnull[0], "%s", a[1]);
    } else if (!strcmp(o, "dist")) {
        snprintf(dists[ndists].name, sizeof dists[0].name, "%s", a[1]);
        dists[ndists++].v = hex(a[2]);
    } else if (!strcmp(o, "col")) {
        Collision *c = block(sizeof *c);

        namef(c, "K%d", count_of('K'), 0);
        c->CollisionTime.PackedTime = hex(a[3]);
        snprintf(cols[ncols].body, sizeof cols[0].body, "%s", a[1]);
        cols[ncols].i = num(a[2]);
        cols[ncols].c = c;
        cols[ncols].car1 = ref(a[4]);
        cols[ncols].car2 = ref(a[5]);
        ncols++;
    } else if (!strcmp(o, "creatorret")) {
        creatorret = ref(a[1]);
    } else if (!strcmp(o, "fill")) {
        fill = (int)hex(a[1]);
    } else if (!strcmp(o, "initsm")) {
        printf("initsm\n");
        init_smokeables();
    } else if (!strcmp(o, "closesm")) {
        printf("closesm\n");
        close_smokeables();
    } else if (!strcmp(o, "spawnall")) {
        printf("spawnall\n");
        spawn_smokeables();
    } else if (!strcmp(o, "clear")) {
        printf("clear\n");
        clear_smokeables();
    } else if (!strcmp(o, "delall")) {
        printf("delall\n");
        delete_smokeable_collision_bodies();
    } else if (!strcmp(o, "farway")) {
        printf("farway\n");
        delete_far_away_smokeable_collision_bodies();
    } else if (!strcmp(o, "register")) {
        SmokeableCreatorFn f = !strcmp(a[2], "basic") ? smokeable_basic_creator
                               : !strcmp(a[2], "stub") ? stub_creator : NULL;

        smokeable_register_creator(num(a[1]), f);
    } else if (!strcmp(o, "creators")) {
        dump_creators();
    } else if (!strcmp(o, "create")) {
        Smokeable *s;

        printf("create %s %s %s %s\n", a[1], a[2], a[3], a[4]);
        s = smokeable_create(num(a[1]), num(a[2]), ref(a[3]), hex(a[4]));
        printf("  -> %s\n", sym(s));
    } else if (!strcmp(o, "spawn")) {
        int32_t r;

        v1.x = bf(hex(a[4]));
        v1.y = bf(hex(a[5]));
        v1.z = bf(hex(a[6]));
        v1.pad = 0.0f;
        printf("spawn %s %s %s %s\n", a[1], a[2], a[3], a[7]);
        r = smokeable_spawn(num(a[1]), ref(a[2]), hex(a[3]), &v1,
                            (uint16_t)num(a[7]));
        printf("  -> %d\n", (int)r);
    } else if (!strcmp(o, "spawnm")) {
        int32_t r;

        setw(&mx, a + 4, 16);
        printf("spawnm %s %s %s\n", a[1], a[2], a[3]);
        r = smokeable_spawn_matrix(num(a[1]), ref(a[2]), hex(a[3]), &mx);
        printf("  -> %d\n", (int)r);
    } else if (!strcmp(o, "delete")) {
        printf("delete %s %s\n", a[1], a[2]);
        smokeable_delete(num(a[1]), ref(a[2]));
    } else if (!strcmp(o, "convert")) {
        CollisionBody *r;

        printf("convert %s\n", a[1]);
        r = smokeable_convert_body(ref(a[1]));
        printf("  -> %s\n", sym(r));
    } else if (!strcmp(o, "vconvert")) {
        Smokeable *r;

        printf("vconvert %s\n", a[1]);
        r = virginsmokeable_convert(ref(a[1]));
        printf("  -> %s\n", sym(r));
    } else if (!strcmp(o, "del")) {
        void          *b = ref(a[1]);
        const VtEntry *e = body_slot(b, COLLISIONBODY_VT_DESTROY);

        printf("del %s %s\n", a[1], a[2]);
        ((DelFn)e->fn)(vt_this(b, e), num(a[2]));
    } else if (!strcmp(o, "sysdel") || !strcmp(o, "sys")) {
        Smokeable     *s = ref(a[1]);
        const VtEntry *e = vt_slot(s->System._vtable,
                                   !strcmp(o, "sys") ? 16 : 8);

        if (!strcmp(o, "sys")) {
            printf("sys %s\n", a[1]);
            ((VoidFn)e->fn)(vt_this(&s->System, e));
        } else {
            printf("sysdel %s %s\n", a[1], a[2]);
            ((DelFn)e->fn)(vt_this(&s->System, e), num(a[2]));
        }
    } else if (!strcmp(o, "move")) {
        void          *b = ref(a[1]);
        const VtEntry *e = body_slot(b, COLLISIONBODY_VT_MOVE);

        printf("move %s %s\n", a[1], a[2]);
        ((MoveFn)e->fn)(vt_this(b, e), bf(hex(a[2])));
    } else if (!strcmp(o, "impulse")) {
        void          *b = ref(a[1]);
        const VtEntry *e = body_slot(b, COLLISIONBODY_VT_CONSIDER_IMPULSE);
        float          f;

        setw(&v1, a + 2, 4);
        setw(&v2, a + 6, 4);
        printf("impulse %s\n", a[1]);
        f = ((ImpulseFn)e->fn)(vt_this(b, e), &v1, &v2);
        printf("  -> %08x\n", fb(f));
    } else if (!strcmp(o, "apply")) {
        void          *b = ref(a[1]);
        const VtEntry *e = body_slot(b, COLLISIONBODY_VT_APPLY_IMPULSE);

        setw(&v1, a + 2, 4);
        setw(&v2, a + 6, 4);
        printf("apply %s\n", a[1]);
        ((ApplyFn)e->fn)(vt_this(b, e), &v1, &v2);
    } else if (!strcmp(o, "sleepchk") || !strcmp(o, "sleep")
               || !strcmp(o, "awaken") || !strcmp(o, "activate")
               || !strcmp(o, "posch") || !strcmp(o, "calib")
               || !strcmp(o, "timers")) {
        Smokeable *s = ref(a[1]);

        printf("%s %s\n", o, a[1]);
        if (!strcmp(o, "sleepchk"))
            smokeable_consider_sleeping(s);
        else if (!strcmp(o, "sleep"))
            smokeable_put_to_sleep(s);
        else if (!strcmp(o, "awaken"))
            smokeable_awaken(s);
        else if (!strcmp(o, "activate"))
            smokeable_activate_anchor_emitters(s);
        else if (!strcmp(o, "posch"))
            smokeable_position_changed(s);
        else if (!strcmp(o, "calib"))
            smokeable_calibrate(s);
        else
            (void)smokeable_check_timers(s);
    } else if (!strcmp(o, "childart") || !strcmp(o, "touching")) {
        Smokeable *s = ref(a[1]);
        int32_t    r;

        printf("%s %s\n", o, a[1]);
        r = !strcmp(o, "childart") ? smokeable_does_child_art_exist(s)
                                   : smokeable_touching_car(s);
        printf("  -> %d\n", (int)r);
    } else if (!strcmp(o, "brk")) {
        DynamicCollisionBody *pieces[4] = { NULL, NULL, NULL, NULL };
        int32_t               r, k;

        printf("brk %s\n", a[1]);
        r = smokeable_break(ref(a[1]), pieces);
        printf("  -> %d", (int)r);
        for (k = 0; k < 4; k++)
            printf(" %s", sym(pieces[k]));
        printf("\n");
    } else if (!strcmp(o, "svc")) {
        setw(&mx, a + 2, 16);
        printf("svc %s\n", a[1]);
        smokeable_service_emitters(ref(a[1]), &mx);
    } else if (!strcmp(o, "setinit")) {
        setw(&mx, a + 2, 16);
        if (strcmp(a[18], "none"))
            setw(&v1, a + 18, 4);
        printf("setinit %s\n", a[1]);
        smokeable_set_initial_position(ref(a[1]), &mx,
                                       strcmp(a[18], "none") ? &v1 : NULL);
    } else if (!strcmp(o, "setgr")) {
        smokeable_set_ground_raise(ref(a[1]), bf(hex(a[2])));
    } else if (!strcmp(o, "blink")) {
        smokeable_set_blinking(ref(a[1]), num(a[2]));
    } else if (!strcmp(o, "acc")) {
        Smokeable *s = ref(a[1]);
        static const int ptrs[] = { 24, 32, 40, 160 };
        static const int ints[] = { 136, 144, 168, 184, 208 };
        static const int flts[] = { 152, 192, 200 };
        const VtEntry   *e;
        int              k;

        printf("acc %s", a[1]);
        for (k = 0; k < 4; k++) {
            e = body_slot(s, ptrs[k]);
            printf(" %s", sym(((PtrFn)e->fn)(vt_this(s, e))));
        }
        for (k = 0; k < 5; k++) {
            e = body_slot(s, ints[k]);
            printf(" %d", (int)((IntFn)e->fn)(vt_this(s, e)));
        }
        for (k = 0; k < 3; k++) {
            e = body_slot(s, flts[k]);
            printf(" %08x", fb(((FloatFn)e->fn)(vt_this(s, e))));
        }
        printf(" %08x", fb(smokeable_get_ground_raise(s)));
        printf(" %s", sym(smokeable_get_topology_coordinate(s)));
        printf(" %08x", fb(smokeable_get_time_alive(s)));
        printf("\n");
        e = body_slot(s, SMOKEABLE_VT_ON_LIFETIME_END);
        ((VoidFn)e->fn)(vt_this(s, e));
    } else if (!strcmp(o, "vacc")) {
        void          *v = ref(a[1]);
        const VtEntry *e1 = body_slot(v, COLLISIONBODY_VT_GET_POSITION);
        const VtEntry *e2 = body_slot(v, COLLISIONBODY_VT_GET_TERRAIN_TYPE);
        const char    *p = sym(((PtrFn)e1->fn)(vt_this(v, e1)));

        printf("vacc %s %s %d\n", a[1], p, (int)((IntFn)e2->fn)(vt_this(v, e2)));
    } else if (!strcmp(o, "vtlife")) {
        Smokeable     *s = ref(a[1]);
        int            n;
        const VtEntry *t = vt_table(SMOKEABLE_VTABLE, &n);

        memcpy(life_vt, t, (size_t)n * sizeof *t);
        life_vt[VT_SLOT(SMOKEABLE_VT_ON_LIFETIME_END)].fn = (VtFn)stub_life_end;
        vt_install(LIFE_VTABLE, life_vt, n);
        s->Dynamic.Body._vtable = LIFE_VTABLE;
    } else if (!strcmp(o, "sf")) {
        smokeable_field(ref(a[1]), a[2], a + 3);
    } else if (!strcmp(o, "rf")) {
        rb_field(ref(a[1]), a[2], a + 3);
    } else if (!strcmp(o, "sd")) {
        dump_smokeable(ref(a[1]));
    } else if (!strcmp(o, "vd")) {
        dump_virgin(ref(a[1]));
    } else if (!strcmp(o, "rd") || !strcmp(o, "rdw")) {
        dump_rb(ref(a[1]), !strcmp(o, "rdw"));
    } else if (!strcmp(o, "ed")) {
        dump_emitter(ref(a[1]));
    } else if (!strcmp(o, "cbl")) {
        dump_cbl();
    } else if (!strcmp(o, "stats")) {
        dump_stats();
    } else if (!strcmp(o, "infos")) {
        dump_infos();
    } else if (!strcmp(o, "vt")) {
        dump_vt();
    } else {
        fprintf(stderr, "unknown op %s\n", o);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[1 << 16];
    FILE       *f;
    int         i;
    char        b[16];

    if (argc != 2) {
        fprintf(stderr, "usage: smokeable_test script.txt\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    name(tok_vp, "VP");
    name(tok_sp, "SP");
    name(tok_rp, "RP");
    name(tok_xp, "XP");
    name(tok_pp, "PP");
    name(tok_world, "W");
    for (i = 0; i < NCARS; i++) {
        snprintf(b, sizeof b, "A%d", i);
        name(tok_cars[i], b);
    }
    name(&CollisionBodyList, "CBL");
    name(&SmokeableInfoList, "SIL");
    name(&WorldEffects, "WE");
    name(&ZeroVector, "ZV");
    name(&ZeroMatrix, "ZM");
    CollisionBodyList.next = CBL_END;
    CollisionBodyList.prev = CBL_END;
    RigidBodySlotPool = (BSlotPool *)(void *)tok_rp;
    pCurrentWorld = (World *)(void *)tok_world;
    TheRaceParameters.NumPlayerCars = 1;
    smokeable_install_vtables();
#ifdef SMOKEABLE_TEST_EXTRA
    extra_init();
#endif
    while (fgets(line, sizeof line, f) != NULL) {
        char *a[48], *s = line;
        int   na = 0;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        while (na < 48) {
            a[na++] = s;
            s = strchr(s, '|');
            if (s == NULL)
                break;
            *s++ = 0;
        }
        op(a, na);
        fflush(stdout);
    }
    fclose(f);
    return 0;
}
