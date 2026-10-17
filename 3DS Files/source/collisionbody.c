// collisionbody -- see collisionbody.h.
//
// CollisionBody.obj, the eleventh slice of task 27 (everything in the
// object that does not move) and the twelfth (DynamicCollisionBody). The
// car-body methods Car reaches are in carcollisionbody.c.

#include "collisionbody.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "eefpu.h"
#include "physicssystem.h"
#include "replay.h"
#include "rigidbody.h"
#include "topology.h"
#include "vtable.h"

// ------------------------------------------------------------ the globals

CollisionStats   TheCollisionStats;
bVector3         ZeroVector;
bMatrix4         IdentityMatrix;
bMatrix4         ZeroMatrix;

CollisionBodyNode        CollisionBodyList;
CollisionBodyWitnessNode CollisionBodyWitnessList;

CollisionBody  **pCollisionBodyTable;
NumberAllocator *pCollisionBodyNumberAllocator;
float            MaxCollisionBodyWidthX;
uint8_t         *pWitnessExistanceBitField;

BSlotPool *TrackPolygonCollisionBodySlotPool;
BSlotPool *CarCollisionBodySlotPool;
BSlotPool *CollisionBodyWitnessSlotPool;

void (*gCollisionDestroyFn)(struct Collision *c, int32_t flags);
CollisionBody *(*gConvertToSmokeableFn)(CollisionBody *b);

// gp-28776, gp-28708 and gp-28704.
#define BBOX_SEED              (-9999999.0f)
#define STATIC_FRICTION        0.3f
#define STATIC_BOUNCINESS      0.1f

// gp-28772, and gp-28768 and gp-28764: the cylinder's margin, and the
// shortest backup Interpolate and InterpolateVelocity will blend over --
// the same 1e-6 (0x358637bd) twice, one for each.
#define CYLINDER_MARGIN        0.05f
#define MIN_BACKUP_TIME        1e-6f

// CreateTrackPolygonCollisionBodies's stack array: 192 bytes of a 304-byte
// frame, and the `slti 48` that guards it.
#define DYN_MAX_TRACK_POLYGONS 48

// The list heads are nodes standing alone. A node is the first thing in
// its record, so a head passes for a body or a witness wherever only the
// links are touched.
#define BODY_END    ((CollisionBody *)(void *)&CollisionBodyList)
#define WITNESS_END ((CollisionBodyWitness *)(void *)&CollisionBodyWitnessList)

static CollisionBodyNode *bnode(CollisionBody *b)
{
    return (CollisionBodyNode *)(void *)b;
}

static CollisionBodyWitnessNode *wnode(CollisionBodyWitness *w)
{
    return (CollisionBodyWitnessNode *)(void *)w;
}

static void body_unlink(CollisionBody *b)
{
    bnode(b->Link.prev)->next = b->Link.next;
    bnode(b->Link.next)->prev = b->Link.prev;
}

// The byte and bit of a pair, `sra` and `andi 7` of ID1 * 206 + ID2.
static int32_t pair_bit(const CollisionBody *a, const CollisionBody *b)
{
    return a->ID * COLLISIONBODY_MAX_BODIES + b->ID;
}

// The image's bStrNCpy (0x0023b378): up to n bytes, stopping after the
// NUL, never padding.
static char *b_strncpy(char *dst, const char *src, int32_t n)
{
    int32_t i;

    for (i = 0; i < n; i++) {
        dst[i] = src[i];
        if (src[i] == 0)
            break;
    }
    return dst;
}

static void stats_up(int32_t *count, int32_t *highest)
{
    (*count)++;
    if (*highest < *count)
        *highest = *count;
}

typedef void (*VtDestroyFn)(void *self, int32_t flags);
typedef int32_t (*VtBoolFn)(void *self);

static void body_virtual_destroy(CollisionBody *b, int32_t flags)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_DESTROY);

    ((VtDestroyFn)e->fn)(vt_this(b, e), flags);
}

void collisionbody_static_init(void)
{
    ZeroVector.x = 0.0f;
    ZeroVector.z = 0.0f;
    ZeroVector.y = 0.0f;
    CollisionBodyList.prev = BODY_END;
    CollisionBodyWitnessList.prev = WITNESS_END;
    CollisionBodyList.next = BODY_END;
    CollisionBodyWitnessList.next = WITNESS_END;
}

void collisionbody_static_close(void)
{
    CollisionBodyWitness *w;
    CollisionBody *b;

    // ~bTList<CollisionBodyWitness>, then ~bTList<CollisionBody>: each
    // record off the list before its destructor, the witness's by name
    // and the body's through its table. bList's own destructor is flags 2,
    // which frees nothing.
    while ((w = CollisionBodyWitnessList.next) != WITNESS_END) {
        wnode(w->Link.prev)->next = w->Link.next;
        wnode(w->Link.next)->prev = w->Link.prev;
        cbwitness_destroy(w, 3);
    }
    while ((b = CollisionBodyList.next) != BODY_END) {
        body_unlink(b);
        body_virtual_destroy(b, 3);
    }
}

// ------------------------------------------------------- NumberAllocator

void numberallocator_set_max_numbers(NumberAllocator *na, int32_t n)
{
    int32_t bytes;

    if (na->MaxNumbers != 0) {
        na->MaxNumbers = 0;
        if (na->pAllocatedBitField != NULL)
            bFree(na->pAllocatedBitField);
        na->pAllocatedBitField = NULL;
        na->LowestFreeNumber = 0;
    }
    if (n == 0)
        return;
    bytes = n >> 3;
    na->MaxNumbers = n;
    na->pAllocatedBitField = bMalloc(bytes + COLLISIONBODY_SHORT_SLACK,
                                     "NumberAllocator", 0, 16);
    memset(na->pAllocatedBitField, 0, (size_t)bytes);
    memset(na->pAllocatedBitField + bytes, 0, COLLISIONBODY_SHORT_SLACK);
    na->LowestFreeNumber = 0;
}

int32_t numberallocator_allocate(NumberAllocator *na)
{
    int32_t i = na->LowestFreeNumber;

    if (i >= na->MaxNumbers)
        return -1;
    numberallocator_allocate_number(na, i);
    return i;
}

void numberallocator_allocate_number(NumberAllocator *na, int32_t i)
{
    if (na->LowestFreeNumber == i) {
        int32_t j = i + 1;

        while (j < na->MaxNumbers
               && (na->pAllocatedBitField[j >> 3] & (1 << (j & 7))) != 0)
            j++;
        na->LowestFreeNumber = j;
    }
    na->pAllocatedBitField[i >> 3] |= (uint8_t)(1 << (i & 7));
}

void numberallocator_free_number(NumberAllocator *na, int32_t i)
{
    na->pAllocatedBitField[i >> 3] &= (uint8_t)~(1 << (i & 7));
    if (i < na->LowestFreeNumber)
        na->LowestFreeNumber = i;
}

void numberallocator_destroy(NumberAllocator *na, int32_t flags)
{
    numberallocator_set_max_numbers(na, 0);
    if (flags & 1)
        bFree(na);
}

// ----------------------------------------------------------- Init / Close

void init_collision_body(void)
{
    NumberAllocator *na;
    size_t table = COLLISIONBODY_MAX_BODIES * sizeof(CollisionBody *);

    CarCollisionBodySlotPool = bNewSlotPool(
        (int)sizeof(CarCollisionBody), 14, "CarCollisionBodySlotPool", 16);
    TrackPolygonCollisionBodySlotPool = bNewSlotPool(
        (int)sizeof(TrackPolygonCollisionBody), 160,
        "TrackPolygonCollisionBodySlotPool", 16);
    CollisionBodyWitnessSlotPool = bNewSlotPool(
        (int)sizeof(CollisionBodyWitness), 256,
        "CollisionBodyWitnessSlotPool", 16);

    na = bMalloc((int)sizeof(NumberAllocator),
                 "CollisionBodyNumberAllocator", 0, 16);
    na->MaxNumbers = 0;
    na->pAllocatedBitField = NULL;
    na->LowestFreeNumber = 0;
    numberallocator_set_max_numbers(na, COLLISIONBODY_MAX_BODIES);
    pCollisionBodyNumberAllocator = na;

    pCollisionBodyTable = bMalloc((int)table, "CollisionBodyTable", 0, 16);
    memset(pCollisionBodyTable, 0, table);
    bIdentity(&IdentityMatrix);
    memset(&ZeroMatrix, 0, sizeof ZeroMatrix);

    pWitnessExistanceBitField = bMalloc(
        COLLISIONBODY_BITFIELD_BYTES + COLLISIONBODY_SHORT_SLACK,
        "CollisionBodyWitnessBitField", 0, 16);
    memset(pWitnessExistanceBitField, 0, COLLISIONBODY_BITFIELD_BYTES);
    memset(pWitnessExistanceBitField + COLLISIONBODY_BITFIELD_BYTES, 0,
           COLLISIONBODY_SHORT_SLACK);
}

void close_collision_body(void)
{
    bDeleteSlotPool(TrackPolygonCollisionBodySlotPool);
    bDeleteSlotPool(CarCollisionBodySlotPool);
    bDeleteSlotPool(CollisionBodyWitnessSlotPool);
    TrackPolygonCollisionBodySlotPool = NULL;
    CarCollisionBodySlotPool = NULL;
    CollisionBodyWitnessSlotPool = NULL;
    if (pCollisionBodyNumberAllocator != NULL)
        numberallocator_destroy(pCollisionBodyNumberAllocator, 3);
    pCollisionBodyNumberAllocator = NULL;
    bFree(pCollisionBodyTable);
    pCollisionBodyTable = NULL;
    if (pWitnessExistanceBitField != NULL)
        bFree(pWitnessExistanceBitField);
    pWitnessExistanceBitField = NULL;
}

// --------------------------------------------------------- CollisionBody

CollisionBody *collisionbody_init(CollisionBody *b, int32_t id, int32_t type)
{
    CollisionBody *head;

    b->_vtable = COLLISIONBODY_VTABLE;
    b->Type = (int8_t)type;
    b->ID = (int16_t)id;
    if (id >= 0) {
        // `sll 16 ; sra 16`: the number is the halfword, as stored.
        numberallocator_allocate_number(pCollisionBodyNumberAllocator,
                                        (int16_t)id);
        pCollisionBodyTable[b->ID] = b;
    }
    stats_up(&TheCollisionStats.NumCollisionBodies,
             &TheCollisionStats.HighestNumCollisionBodies);
    b->DebugName[0] = 0;

    head = CollisionBodyList.next;
    CollisionBodyList.next = b;
    bnode(head)->prev = b;
    b->BBoxMax.y = BBOX_SEED;
    b->Link.prev = BODY_END;
    b->Link.next = head;
    b->pCaffeineObj = NULL;
    b->BBoxMin.x = BBOX_SEED;
    b->BBoxMin.y = BBOX_SEED;
    b->BBoxMax.x = BBOX_SEED;
    b->CollisionsDisabled = 0;
    b->NumCollisions = 0;
    b->NumWitnesses = 0;
    b->ActiveCollisionDetection = 0;
    return b;
}

void collisionbody_destroy(CollisionBody *b, int32_t flags)
{
    b->_vtable = COLLISIONBODY_VTABLE;
    TheCollisionStats.NumCollisionBodies--;
    collisionbody_update_max_width(b, 0.0f);
    body_unlink(b);

    if (b->NumWitnesses != 0) {
        CollisionBodyWitness *w = CollisionBodyWitnessList.next;

        while (w != WITNESS_END) {
            CollisionBodyWitness *next = w->Link.next;

            if (w->pBody1 == b || w->pBody2 == b)
                cbwitness_destroy(w, 3);
            w = next;
        }
    }
    if (b->ID >= 0) {
        pCollisionBodyTable[b->ID] = NULL;
        numberallocator_free_number(pCollisionBodyNumberAllocator, b->ID);
    }
    // ~bTNode, which is bNode's: __builtin_delete when flags & 1.
    if (flags & 1)
        bFree(b);
}

int32_t collisionbody_flip_function(const CollisionBody *a,
                                    const CollisionBody *b)
{
    if (b->BBoxMax.x < a->BBoxMax.x)
        return 1;
    if (a->BBoxMax.x < b->BBoxMax.x)
        return 0;
    return b->ID < a->ID;
}

void collisionbody_update_max_width(CollisionBody *b, float w)
{
    float cur = b->BBoxMax.x - b->BBoxMin.x;
    float widest;
    CollisionBody *o;

    if (w == cur)
        return;
    if (cur < w && MaxCollisionBodyWidthX < w) {
        MaxCollisionBodyWidthX = w;
        return;
    }
    if (!(w < cur) || !(cur == MaxCollisionBodyWidthX))
        return;

    // b was the widest and is narrowing: the widest of the others.
    widest = 0.0f;
    for (o = CollisionBodyList.next; o != BODY_END; o = o->Link.next) {
        float ow;

        if (o == b)
            continue;
        ow = o->BBoxMax.x - o->BBoxMin.x;
        if (widest < ow)
            widest = ow;
    }
    MaxCollisionBodyWidthX = widest;
}

void collisionbody_set_bbox_min_max(CollisionBody *b, const bVector2 *min,
                                    const bVector2 *max)
{
    float x, y, old;

    collisionbody_update_max_width(b, max->x - min->x);
    y = min->y;
    x = min->x;
    b->BBoxMin.y = y;
    b->BBoxMin.x = x;
    old = b->BBoxMax.x;
    x = max->x;
    y = max->y;
    b->BBoxMax.x = x;
    b->BBoxMax.y = y;
    if (old == max->x)
        return;

    // One step at a time, toward the head while the one before should
    // follow b, then toward the tail while the one after should lead it;
    // the look starts again from the top after every step.
    for (;;) {
        CollisionBody *prev = b->Link.prev;
        CollisionBody *next = b->Link.next;

        if (prev != BODY_END && collisionbody_flip_function(prev, b)) {
            CollisionBody *pp;

            body_unlink(b);
            pp = prev->Link.prev;
            bnode(pp)->next = b;
            prev->Link.prev = b;
            b->Link.prev = pp;
            b->Link.next = prev;
            continue;
        }
        if (next == BODY_END || !collisionbody_flip_function(b, next))
            return;
        {
            CollisionBody *nn;

            body_unlink(b);
            nn = next->Link.next;
            next->Link.next = b;
            bnode(nn)->prev = b;
            b->Link.prev = next;
            b->Link.next = nn;
        }
    }
}

void collisionbody_plot_to_caffeine(CollisionBody *b, const bMatrix4 *m,
                                    const bVector3 *t)
{
    (void)b;
    (void)m;
    (void)t;
}

int32_t collisionbody_get_next_id(void)
{
    return (uint16_t)pCollisionBodyNumberAllocator->LowestFreeNumber;
}

void collisionbody_set_debug_name(CollisionBody *b, const char *name)
{
    b_strncpy(b->DebugName, name, (int32_t)sizeof b->DebugName);
    b->DebugName[sizeof b->DebugName - 1] = 0;
}

void collisionbody_debug_print(CollisionBody *b)
{
    (void)b;
}

void collisionbody_maybe_print_all(void)
{
}

CollisionBody *collisionbody_find(int32_t i)
{
    return pCollisionBodyTable[i];
}

struct Collision *collisionbody_get_collision(CollisionBody *b, int32_t i)
{
    CollisionBodyWitness *w;
    int32_t n = 0;

    if (!(i < b->NumCollisions))
        return NULL;
    for (w = CollisionBodyWitnessList.next; w != WITNESS_END;
         w = w->Link.next) {
        if (w->pCollision == NULL)
            continue;
        if (w->pBody1 != b && w->pBody2 != b)
            continue;
        if (n == i)
            return w->pCollision;
        n++;
    }
    return NULL;
}

void collisionbody_enable_collisions(CollisionBody *b)
{
    if (b->CollisionsDisabled != 0)
        b->CollisionsDisabled = (int8_t)(b->CollisionsDisabled - 1);
}

void collisionbody_disable_collisions(CollisionBody *b)
{
    b->CollisionsDisabled = (int8_t)(b->CollisionsDisabled + 1);
}

int32_t collisionbody_is_blinking(CollisionBody *b)
{
    (void)b;
    return 0;
}

int32_t collisionbody_do_bbox_check(const CollisionBody *b,
                                    const bVector2 *min, const bVector2 *max,
                                    float margin)
{
    return b->BBoxMin.x <= max->x + margin
        && min->x - margin <= b->BBoxMax.x
        && b->BBoxMin.y <= max->y + margin
        && min->y - margin <= b->BBoxMax.y;
}

int32_t collisionbody_do_bbox_check_body(const CollisionBody *b,
                                         const CollisionBody *other,
                                         float margin)
{
    return b->BBoxMin.x <= other->BBoxMax.x + margin
        && other->BBoxMin.x - margin <= b->BBoxMax.x
        && b->BBoxMin.y <= other->BBoxMax.y + margin
        && other->BBoxMin.y - margin <= b->BBoxMax.y;
}

// ---------------------------------------------------- StaticCollisionBody

StaticCollisionBody *staticcollisionbody_init(StaticCollisionBody *s,
                                              int32_t id, int32_t type)
{
    collisionbody_init(&s->Body, id, type);
    stats_up(&TheCollisionStats.NumStaticCollisionBodies,
             &TheCollisionStats.HighestNumStaticCollisionBodies);
    s->Body._vtable = STATICCOLLISIONBODY_VTABLE;
    s->Body.Dynamic = 0;
    return s;
}

void staticcollisionbody_destroy(StaticCollisionBody *s, int32_t flags)
{
    s->Body._vtable = STATICCOLLISIONBODY_VTABLE;
    TheCollisionStats.NumStaticCollisionBodies--;
    collisionbody_destroy(&s->Body, flags);
}

bVector3 *staticcollisionbody_get_velocity(CollisionBody *b)
{
    (void)b;
    return &ZeroVector;
}

bMatrix4 *staticcollisionbody_get_rotation(CollisionBody *b)
{
    (void)b;
    return &IdentityMatrix;
}

void staticcollisionbody_set_position(CollisionBody *b, bVector3 *p)
{
    (void)b;
    (void)p;
}

float staticcollisionbody_get_max_backup_time(CollisionBody *b)
{
    (void)b;
    return 1000.0f;
}

void staticcollisionbody_move(CollisionBody *b, float t)
{
    (void)b;
    (void)t;
}

void staticcollisionbody_backup(CollisionBody *b, float t)
{
    (void)b;
    (void)t;
}

// Four quadword loads of the matrix, four stores, then the vector: all
// sixteen bytes of each, the fourth lanes too.
void staticcollisionbody_interpolate(CollisionBody *b, bVector3 *pos,
                                     bMatrix4 *rot, float t)
{
    bMatrix4 m = IdentityMatrix;

    (void)b;
    (void)t;
    *rot = m;
    *pos = ZeroVector;
}

void staticcollisionbody_recompute_auxilliaries(CollisionBody *b)
{
    (void)b;
}

void staticcollisionbody_get_current_velocities(CollisionBody *b,
                                                bVector3 *v, bVector3 *w)
{
    (void)b;
    *v = ZeroVector;
    *w = ZeroVector;
}

// Four references, and only the first two written.
void staticcollisionbody_get_test_impulse_velocities(CollisionBody *b,
                                                     bVector3 *v,
                                                     bVector3 *w,
                                                     bVector3 *a,
                                                     bVector3 *c)
{
    (void)b;
    (void)a;
    (void)c;
    *v = ZeroVector;
    *w = ZeroVector;
}

void staticcollisionbody_set_to_physics_mode(CollisionBody *b,
                                             CollisionBody *other)
{
    (void)b;
    (void)other;
}

float staticcollisionbody_consider_impulse(CollisionBody *b, bVector3 *point,
                                           bVector3 *impulse)
{
    (void)b;
    (void)point;
    (void)impulse;
    return 1.0f;
}

void staticcollisionbody_apply_impulse(CollisionBody *b, bVector3 *point,
                                       bVector3 *impulse)
{
    (void)b;
    (void)point;
    (void)impulse;
}

int32_t staticcollisionbody_are_collisions_enabled(CollisionBody *b)
{
    return b->CollisionsDisabled == 0;
}

float staticcollisionbody_get_mass_inverse(CollisionBody *b)
{
    (void)b;
    return 0.0f;
}

bMatrix4 *staticcollisionbody_get_inertia_tensor_inverse(CollisionBody *b)
{
    (void)b;
    return &ZeroMatrix;
}

int32_t staticcollisionbody_is_moveable(CollisionBody *b)
{
    (void)b;
    return 0;
}

float staticcollisionbody_change_in_energy(CollisionBody *b, bVector3 *point,
                                           bVector3 *impulse)
{
    (void)b;
    (void)point;
    (void)impulse;
    return 0.0f;
}

float staticcollisionbody_get_bounciness(CollisionBody *b)
{
    (void)b;
    return STATIC_BOUNCINESS;
}

float staticcollisionbody_get_friction(CollisionBody *b)
{
    (void)b;
    return STATIC_FRICTION;
}

// ---------------------------------------------- TrackPolygonCollisionBody

TrackPolygonCollisionBody *trackpolygoncollisionbody_init(
    TrackPolygonCollisionBody *t, int32_t id, TopologyTreePolygon *p)
{
    CollisionBody *b = &t->Static.Body;
    char name[32];
    bVector3 origin;
    bMatrix4 m;
    TrackPolygon *tp;

    staticcollisionbody_init(&t->Static, id, TRACK_POLYGON_COLLISION_BODY);
    b->_vtable = TRACKPOLYGONCOLLISIONBODY_VTABLE;
    vcpoly_init(&t->Wafer.Poly);
    stats_up(&TheCollisionStats.NumTrackPolygonCollisionBodies,
             &TheCollisionStats.HighestNumTrackPolygonCollisionBodies);
    b->pPoly = &t->Wafer.Poly;

    // bSPrintf, which the port does not have; the index is `subu ; sra 5`
    // of the two addresses, and a TopologyTreePolygon is 32 bytes on both.
    snprintf(name, sizeof name, "TrackPolygon%d",
             (int)(((char *)p - (char *)TheTopologyTree.pPolygonTable) >> 5));
    collisionbody_set_debug_name(b, name);

    tp = topotree_assign(&TheTopologyTree, p);
    t->pTP = tp;
    tp->pCollisionBody = t;
    // The fourth lane is stack junk on the console; Init reads only three.
    memset(&origin, 0, sizeof origin);
    waferpoly_init(&t->Wafer, tp, &origin);
    collisionbody_set_bbox_min_max(b, &t->pTP->BBoxMin, &t->pTP->BBoxMax);
    bIdentity(&m);
    collisionbody_plot_to_caffeine(b, &m, &origin);
    return t;
}

void trackpolygoncollisionbody_destroy(TrackPolygonCollisionBody *t,
                                       int32_t flags)
{
    TrackPolygon *tp;

    t->Static.Body._vtable = TRACKPOLYGONCOLLISIONBODY_VTABLE;
    tp = t->pTP;
    tp->pCollisionBody = NULL;
    topotree_unassign(&TheTopologyTree, tp);
    TheCollisionStats.NumTrackPolygonCollisionBodies--;
    waferpoly_destroy(&t->Wafer, 2);
    staticcollisionbody_destroy(&t->Static, 0);
    if (flags & 1)
        trackpolygoncollisionbody_delete(t);
}

void *trackpolygoncollisionbody_new(void)
{
    return bSlotOMalloc(TrackPolygonCollisionBodySlotPool);
}

void trackpolygoncollisionbody_delete(void *p)
{
    bSlotFree(TrackPolygonCollisionBodySlotPool, p);
}

bVector3 *trackpolygoncollisionbody_get_position(CollisionBody *b)
{
    (void)b;
    return &ZeroVector;
}

int32_t trackpolygoncollisionbody_get_terrain_type(CollisionBody *b)
{
    return (int8_t)((TrackPolygonCollisionBody *)b)->pTP->TheTerrainType;
}

TrackPolygon *trackpolygoncollisionbody_get_track_polygon(
    TrackPolygonCollisionBody *t)
{
    return t->pTP;
}

// --------------------------------------------------- CollisionBodyWitness

CollisionBodyWitness *cbwitness_init(CollisionBodyWitness *w,
                                     CollisionBody *b1, CollisionBody *b2)
{
    CollisionBodyWitness *tail;
    int32_t k;

    vcwitness_init(&w->Witness, b1->pPoly, b2->pPoly);
    stats_up(&TheCollisionStats.NumCollisionBodyWitnesses,
             &TheCollisionStats.HighestNumCollisionBodyWitnesses);

    tail = CollisionBodyWitnessList.prev;
    w->pBody1 = b1;
    wnode(tail)->next = w;
    CollisionBodyWitnessList.prev = w;
    w->pBody2 = b2;
    w->Link.prev = tail;
    w->Link.next = WITNESS_END;
    w->pCollision = NULL;

    k = pair_bit(b1, b2);
    pWitnessExistanceBitField[k >> 3] |= (uint8_t)(1 << (k & 7));
    k = pair_bit(w->pBody2, w->pBody1);
    pWitnessExistanceBitField[k >> 3] |= (uint8_t)(1 << (k & 7));
    w->pBody1->NumWitnesses = (int8_t)(w->pBody1->NumWitnesses + 1);
    w->pBody2->NumWitnesses = (int8_t)(w->pBody2->NumWitnesses + 1);
    return w;
}

// A track polygon's body is made for the witnesses and lives while it has
// one; each end is looked at in turn, and the pointer is cleared once the
// body is gone.
static void maybe_destroy_track_body(CollisionBody **end)
{
    CollisionBody *b = *end;

    if (b->Type != TRACK_POLYGON_COLLISION_BODY || b->NumWitnesses != 0)
        return;
    if (b != NULL)
        body_virtual_destroy(b, 3);
    *end = NULL;
}

void cbwitness_destroy(CollisionBodyWitness *w, int32_t flags)
{
    int32_t k;

    TheCollisionStats.NumCollisionBodyWitnesses--;
    if (w->pCollision != NULL)
        cbwitness_end_collision(w);

    wnode(w->Link.prev)->next = w->Link.next;
    wnode(w->Link.next)->prev = w->Link.prev;
    w->pBody1->NumWitnesses = (int8_t)(w->pBody1->NumWitnesses - 1);
    w->pBody2->NumWitnesses = (int8_t)(w->pBody2->NumWitnesses - 1);
    k = pair_bit(w->pBody1, w->pBody2);
    pWitnessExistanceBitField[k >> 3] &= (uint8_t)~(1 << (k & 7));
    k = pair_bit(w->pBody2, w->pBody1);
    pWitnessExistanceBitField[k >> 3] &= (uint8_t)~(1 << (k & 7));

    maybe_destroy_track_body(&w->pBody1);
    maybe_destroy_track_body(&w->pBody2);

    vcwitness_destroy(&w->Witness, 0);
    // ~bTNode with flags 0 does nothing.
    if (flags & 1)
        cbwitness_delete(w);
}

void cbwitness_delete(void *p)
{
    bSlotFree(CollisionBodyWitnessSlotPool, p);
}

void cbwitness_end_collision(CollisionBodyWitness *w)
{
    if (w->pCollision != NULL) {
        if (gCollisionDestroyFn == NULL) {
            fprintf(stderr, "cbwitness_end_collision: Collision is not "
                            "ported\n");
            abort();
        }
        gCollisionDestroyFn(w->pCollision, 3);
    }
    w->pCollision = NULL;
    TheCollisionStats.NumCollisions--;
    w->pBody1->NumCollisions = (int8_t)(w->pBody1->NumCollisions - 1);
    w->pBody2->NumCollisions = (int8_t)(w->pBody2->NumCollisions - 1);
}

static int32_t are_collisions_enabled(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable,
                               COLLISIONBODY_VT_ARE_COLLISIONS_ENABLED);

    return ((VtBoolFn)e->fn)(vt_this(b, e));
}

int32_t cbwitness_has_expired(CollisionBodyWitness *w)
{
    CollisionBody *b1, *b2;

    if (w->pCollision != NULL)
        return 0;
    b1 = w->pBody1;
    b2 = w->pBody2;
    if (!(b1->BBoxMin.x <= b2->BBoxMax.x && b2->BBoxMin.x <= b1->BBoxMax.x
          && b1->BBoxMin.y <= b2->BBoxMax.y
          && b2->BBoxMin.y <= b1->BBoxMax.y))
        return 1;
    if (b1->ActiveCollisionDetection == 0
        && b2->ActiveCollisionDetection == 0)
        return 1;
    if (!are_collisions_enabled(b1))
        return 1;
    if (!are_collisions_enabled(w->pBody2))
        return 1;
    return 0;
}

int32_t is_yaw_control_inducing_collision_body(const CollisionBody *b)
{
    if (b->Type < 0)
        return 0;
    if (b->Type < TRACK_POLYGON_COLLISION_BODY)
        return 1;
    if (b->Type == TRACK_POLYGON_COLLISION_BODY)
        return (((const TrackPolygonCollisionBody *)b)->pTP->Flags
                & TRACKPOLY_VERTICAL) != 0;
    return 0;
}

void cbwitness_eliminate_all(void)
{
    CollisionBodyWitness *w;

    while ((w = CollisionBodyWitnessList.next) != WITNESS_END)
        if (w != NULL)
            cbwitness_destroy(w, 3);
}

void cbwitness_debug_print(CollisionBodyWitness *w)
{
    (void)w;
}

int32_t cbwitness_does_witness_exist(const CollisionBody *a,
                                     const CollisionBody *b)
{
    int32_t k;

    if (a->ID < 0 || b->ID < 0)
        return 0;
    k = pair_bit(a, b);
    return pWitnessExistanceBitField[k >> 3] & (1 << (k & 7));
}

// --------------------------------------------------- DynamicCollisionBody

typedef bVector3 *(*VtVectorFn)(void *self);
typedef bMatrix4 *(*VtMatrixFn)(void *self);
typedef void (*VtInterpolateFn)(void *self, bVector3 *pos, bMatrix4 *rot,
                                float t);

// Slots 24, 32 and 40, which DynamicCollisionBody leaves to the class
// under it.
static bVector3 *body_get_position(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_POSITION);

    return ((VtVectorFn)e->fn)(vt_this(b, e));
}

static bVector3 *body_get_velocity(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_VELOCITY);

    return ((VtVectorFn)e->fn)(vt_this(b, e));
}

static bMatrix4 *body_get_rotation(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_ROTATION);

    return ((VtMatrixFn)e->fn)(vt_this(b, e));
}

// vsub.xyzw: now - back in all four lanes, the pad too.
static void lanes_sub(float d[4], const void *now, const void *back)
{
    float a[4], b[4];
    int i;

    memcpy(a, now, sizeof a);
    memcpy(b, back, sizeof b);
    for (i = 0; i < 4; i++)
        d[i] = a[i] - b[i];
}

// vmulx.xyzw, vadd.xyzw, sqc2: d * f + back, all sixteen bytes stored.
static void lanes_blend(void *out, const float d[4], float f,
                        const void *back)
{
    float b[4], r[4];
    int i;

    memcpy(b, back, sizeof b);
    for (i = 0; i < 4; i++)
        r[i] = d[i] * f + b[i];
    memcpy(out, r, sizeof r);
}

// The four compares the image inlines wherever a box meets another,
// inclusive and with no margin: b's box against [min, max].
static int32_t box_touches(const CollisionBody *b, const bVector2 *min,
                           const bVector2 *max)
{
    return b->BBoxMin.x <= max->x && min->x <= b->BBoxMax.x
        && b->BBoxMin.y <= max->y && min->y <= b->BBoxMax.y;
}

static CollisionBody *convert_to_smokeable(CollisionBody *b)
{
    if (gConvertToSmokeableFn == NULL) {
        fprintf(stderr, "convert_to_smokeable: Smokeable is not ported\n");
        abort();
    }
    return gConvertToSmokeableFn(b);
}

// bOMalloc of the witness pool. The image hands a NULL on to the
// constructor, which writes through it; the port stops.
static CollisionBodyWitness *witness_new(void)
{
    CollisionBodyWitness *w = bSlotOMalloc(CollisionBodyWitnessSlotPool);

    if (w == NULL) {
        fprintf(stderr, "witness_new: CollisionBodyWitnessSlotPool is "
                        "full\n");
        abort();
    }
    return w;
}

DynamicCollisionBody *dynamiccollisionbody_init(DynamicCollisionBody *d,
                                                int32_t id, int32_t type,
                                                TopologyCoordinate *tc)
{
    collisionbody_init(&d->Body, id, type);
    stats_up(&TheCollisionStats.NumDynamicCollisionBodies,
             &TheCollisionStats.HighestNumDynamicCollisionBodies);
    d->Body._vtable = DYNAMICCOLLISIONBODY_VTABLE;
    d->pTC = tc;
    d->Body.Dynamic = 1;
    d->pSystem = NULL;
    d->pBody = NULL;
    d->PhysicsMode = 0;
    return d;
}

void dynamiccollisionbody_destroy(DynamicCollisionBody *d, int32_t flags)
{
    d->Body._vtable = DYNAMICCOLLISIONBODY_VTABLE;
    TheCollisionStats.NumDynamicCollisionBodies--;
    collisionbody_destroy(&d->Body, flags);
}

// Each extreme is `if (hi < v) hi = v; else if (v < lo) lo = v;`, and
// every one starts at zero. The roots are of sums of squares, never below
// zero, so they are plain ones.
void dynamiccollisionbody_build_bounding_volumes(DynamicCollisionBody *d)
{
    const VCPolyhedron *poly = d->Body.pPoly;
    const VCVertex *v = poly->pVertices;
    int32_t n = poly->NumVertices;
    int32_t i;
    float radius = 0.0f, cylinder = 0.0f, top = 0.0f, base = 0.0f;
    float hix = 0.0f, lox = 0.0f, hiy = 0.0f, loy = 0.0f;
    float hiz = 0.0f, loz = 0.0f;

    for (i = 0; i < n; i++, v++) {
        float x = v->CompressedPosition[0];
        float y = v->CompressedPosition[1];
        float z = v->CompressedPosition[2];
        float xy = x * x + y * y;
        float r2 = sqrtf(xy);
        float r3 = sqrtf(xy + z * z);

        if (radius < r3)
            radius = r3;
        if (cylinder < r2)
            cylinder = r2;
        if (top < z)
            top = z;
        else if (z < base)
            base = z;
        if (hix < x)
            hix = x;
        else if (x < lox)
            lox = x;
        if (hiy < y)
            hiy = y;
        else if (y < loy)
            loy = y;
        if (hiz < z)
            hiz = z;
        else if (z < loz)
            loz = z;
    }
    d->CylinderBaseHeight = CYLINDER_MARGIN - base;
    d->CylinderTopHeight = top + CYLINDER_MARGIN;
    d->CylinderRadius = cylinder + CYLINDER_MARGIN;
    d->Radius = radius;
    d->LocalBBMin.x = lox;
    d->LocalBBMin.y = loy;
    d->LocalBBMin.z = loz;
    d->LocalBBMax.x = hix;
    d->LocalBBMax.y = hiy;
    d->LocalBBMax.z = hiz;
}

void dynamiccollisionbody_update_position(DynamicCollisionBody *d)
{
    bVector3 *p = body_get_position(&d->Body);
    float r = d->CylinderRadius;
    bVector2 min, max;

    min.x = p->x - r;
    min.y = p->y - r;
    max.y = p->y + r;
    max.x = p->x + r;
    collisionbody_set_bbox_min_max(&d->Body, &min, &max);
}

void dynamiccollisionbody_begin_move(DynamicCollisionBody *d, float t)
{
    bMatrix4 m = *body_get_rotation(&d->Body);

    d->BackupRotation = m;
    d->BackupPosition = *body_get_position(&d->Body);
    d->BackupVelocity = *body_get_velocity(&d->Body);
    d->BackupTime = t;
}

// Every difference is taken, then every blend stored: the position first,
// then the rows in order.
void dynamiccollisionbody_interpolate(CollisionBody *b, bVector3 *pos,
                                      bMatrix4 *rot, float t)
{
    DynamicCollisionBody *d = (DynamicCollisionBody *)b;
    bVector3 *p = body_get_position(b);
    bMatrix4 *r = body_get_rotation(b);
    float dp[4], d0[4], d1[4], d2[4], d3[4], f;

    if (d->BackupTime < MIN_BACKUP_TIME) {
        bMatrix4 m;

        *pos = *p;
        m = *r;
        *rot = m;
        return;
    }
    lanes_sub(dp, p, &d->BackupPosition);
    lanes_sub(d0, &r->v0, &d->BackupRotation.v0);
    lanes_sub(d1, &r->v1, &d->BackupRotation.v1);
    lanes_sub(d2, &r->v2, &d->BackupRotation.v2);
    lanes_sub(d3, &r->v3, &d->BackupRotation.v3);
    f = (d->BackupTime - t) / d->BackupTime;
    lanes_blend(pos, dp, f, &d->BackupPosition);
    lanes_blend(&rot->v0, d0, f, &d->BackupRotation.v0);
    lanes_blend(&rot->v1, d1, f, &d->BackupRotation.v1);
    lanes_blend(&rot->v2, d2, f, &d->BackupRotation.v2);
    lanes_blend(&rot->v3, d3, f, &d->BackupRotation.v3);
}

void dynamiccollisionbody_interpolate_velocity(DynamicCollisionBody *d,
                                               bVector3 *out, float t)
{
    float dv[4], f;
    bVector3 *v;

    if (d->BackupTime < MIN_BACKUP_TIME) {
        *out = *body_get_velocity(&d->Body);
        return;
    }
    f = (d->BackupTime - t) / d->BackupTime;
    v = body_get_velocity(&d->Body);
    lanes_sub(dv, v, &d->BackupVelocity);
    lanes_blend(out, dv, f, &d->BackupVelocity);
}

// Interpolate is the table's; InterpolateVelocity is called by name.
void dynamiccollisionbody_backup(CollisionBody *b, float t)
{
    DynamicCollisionBody *d = (DynamicCollisionBody *)b;
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_INTERPOLATE);
    RigidBody *rb;
    bVector3 pos, vel;
    bMatrix4 rot;
    float m;

    ((VtInterpolateFn)e->fn)(vt_this(b, e), &pos, &rot, t);
    dynamiccollisionbody_interpolate_velocity(d, &vel, t);
    rb = d->pBody;
    m = rb->Mass;
    vel.x = vel.x * m;
    vel.y = vel.y * m;
    vel.z = vel.z * m;
    vel.pad = vel.pad * m;
    memcpy(&rb->State.X, &pos, sizeof rb->State.X);
    memcpy(&rb->State.R, &rot, sizeof rb->State.R);
    memcpy(&rb->State.P, &vel, sizeof rb->State.P);
}

void dynamiccollisionbody_recompute_auxilliaries(CollisionBody *b)
{
    PhysicsSystem *s = ((DynamicCollisionBody *)b)->pSystem;
    const VtEntry *e = vt_slot(s->_vtable,
                               PHYSICSSYSTEM_VT_COMPUTE_AUXILIARIES);

    ((PhysicsVoidFn)e->fn)(vt_this(s, e));
}

void dynamiccollisionbody_get_current_velocities(CollisionBody *b,
                                                 bVector3 *v, bVector3 *w)
{
    RigidBody *rb = ((DynamicCollisionBody *)b)->pBody;

    memcpy(v, &rb->Velocity, sizeof *v);
    memcpy(w, &rb->AngularVelocity, sizeof *w);
}

void dynamiccollisionbody_get_test_impulse_velocities(CollisionBody *b,
                                                      bVector3 *v,
                                                      bVector3 *w,
                                                      bVector3 *j,
                                                      bVector3 *at)
{
    rigidbody_test_impulse(((DynamicCollisionBody *)b)->pBody,
                           (bVector4 *)v, (bVector4 *)w,
                           (const bVector4 *)j, (const bVector4 *)at);
}

void dynamiccollisionbody_get_local_collision_bodies(DynamicCollisionBody *d,
                                                     float margin,
                                                     CollisionBody **first,
                                                     CollisionBody **last)
{
    CollisionBody *b = &d->Body;
    float lo = b->BBoxMin.x - margin;
    float hi;

    *first = b->Link.prev;
    while (*first != BODY_END && lo <= (*first)->BBoxMax.x)
        *first = (*first)->Link.prev;
    hi = b->BBoxMax.x + margin;
    *last = b->Link.next;
    while (*last != BODY_END && (*last)->BBoxMin.x <= hi)
        *last = (*last)->Link.next;
}

void dynamiccollisionbody_maybe_create_witnesses(DynamicCollisionBody *d)
{
    CollisionBody *b = &d->Body;
    CollisionBody *lo, *end, *o, *next;
    float reach;

    if (!are_collisions_enabled(b))
        return;
    dynamiccollisionbody_create_track_polygon_collision_bodies(d);

    // Back to the first body that ends before this one starts; then on to
    // the first that ends past this one's end by more than the widest body
    // is wide, which is read after the track polygons' bodies are made.
    lo = b->Link.prev;
    while (lo != BODY_END && b->BBoxMin.x <= lo->BBoxMax.x)
        lo = lo->Link.prev;
    reach = b->BBoxMax.x + MaxCollisionBodyWidthX;
    end = b->Link.next;
    while (end != BODY_END && end->BBoxMax.x <= reach)
        end = end->Link.next;

    // The image loads CollisionBodyList.next when lo is the head, which is
    // the head's own next.
    for (o = lo->Link.next; o != end; o = next) {
        CollisionBody *other = o;

        next = o->Link.next;
        if (o == b || !box_touches(b, &o->BBoxMin, &o->BBoxMax))
            continue;
        if (cbwitness_does_witness_exist(b, o))
            continue;
        if (!are_collisions_enabled(o))
            continue;
        if (o->Type == VIRGIN_SMOKEABLE_COLLISION_BODY)
            other = convert_to_smokeable(o);
        if (other == NULL
            || !box_touches(b, &other->BBoxMin, &other->BBoxMax))
            continue;
        cbwitness_init(witness_new(), b, other);
    }
}

int32_t dynamiccollisionbody_create_track_polygon_collision_bodies(
    DynamicCollisionBody *d)
{
    CollisionBody *b = &d->Body;
    TrackPolygon *near[DYN_MAX_TRACK_POLYGONS];
    int32_t total = d->pTC->TotalNumTrackPolygons;
    int32_t n = 0, i, swaps;

    for (i = 0; i < total; i++) {
        TrackPolygon *tp = d->pTC->TrackPolygonTable[i];

        if (tp->pCollisionBody != NULL)
            continue;
        if (!box_touches(b, &tp->BBoxMin, &tp->BBoxMax))
            continue;
        if (!dynamiccollisionbody_track_polygon_check(d, tp))
            continue;
        if (n < DYN_MAX_TRACK_POLYGONS)
            near[n++] = tp;
    }
    if (n == 0)
        return 0;

    // A bubble sort by the tree polygon's address -- `sltu`, whole passes
    // until one swaps nothing. The polygons are one table, so the address
    // order is the index order.
    do {
        swaps = 0;
        for (i = 0; i < n - 1; i++) {
            if (near[i + 1]->pPolygon < near[i]->pPolygon) {
                TrackPolygon *t = near[i];

                near[i] = near[i + 1];
                near[i + 1] = t;
                swaps++;
            }
        }
    } while (swaps != 0);

    for (i = 0; i < n; i++) {
        TopologyTreePolygon *p;
        TrackPolygonCollisionBody *t;
        int32_t id;

        if (bIsSlotPoolFull(TrackPolygonCollisionBodySlotPool))
            return i;
        p = near[i]->pPolygon;
        id = collisionbody_get_next_id();
        t = trackpolygoncollisionbody_init(trackpolygoncollisionbody_new(),
                                           id, p);
        // Then a box test of the new body against this one whose answer
        // the image drops, which is left out.
        if (cbwitness_does_witness_exist(b, &t->Static.Body))
            collisionbody_debug_print(&t->Static.Body);
    }
    return n;
}

// The two heights and the radius are read before the table is called, the
// top height only when it is wanted.
int32_t dynamiccollisionbody_track_polygon_check(DynamicCollisionBody *d,
                                                 TrackPolygon *tp)
{
    CollisionBody *b = &d->Body;
    const TrackPolygonNormal *n = &tp->Normal;
    float h = d->CylinderBaseHeight;
    float r = d->CylinderRadius;
    bMatrix4 *rot = body_get_rotation(b);
    float up = (rot->v2.x * n->x + rot->v2.y * n->y) + rot->v2.z * n->z;
    float s = ee_sqrt(1.0f - up * up);
    bVector3 *p = body_get_position(b);
    float dist = ((p->x * n->x + p->y * n->y) + p->z * n->z)
                 - tp->PlaneDistance;

    if (up * dist < 0.0f)
        h = d->CylinderTopHeight;
    return fabsf(dist) < fabsf(up) * h + s * r;
}

float dynamiccollisionbody_change_in_energy(CollisionBody *b, bVector3 *j,
                                            bVector3 *at)
{
    DynamicCollisionBody *d = (DynamicCollisionBody *)b;
    float after = rigidbody_get_test_impulse_energy(
        d->pBody, (const bVector4 *)j, (const bVector4 *)at);

    return after - rigidbody_get_energy(d->pBody);
}

void dynamiccollisionbody_get_bounding_box(DynamicCollisionBody *d,
                                           bVector3 *min, bVector3 *max)
{
    *min = d->LocalBBMin;
    *max = d->LocalBBMax;
}

void dynamiccollisionbody_apply_impulse(CollisionBody *b, bVector3 *j,
                                        bVector3 *at)
{
    rigidbody_apply_impulse(((DynamicCollisionBody *)b)->pBody,
                            (const bVector4 *)j, (const bVector4 *)at);
}

bMatrix4 *dynamiccollisionbody_get_inertia_tensor_inverse(CollisionBody *b)
{
    return &((RigidBody *)((DynamicCollisionBody *)b)->pBody)->I_body_inv;
}

float dynamiccollisionbody_get_mass_inverse(CollisionBody *b)
{
    return ((RigidBody *)((DynamicCollisionBody *)b)->pBody)->Mass_inv;
}

void dynamiccollisionbody_set_to_physics_mode(CollisionBody *b,
                                              CollisionBody *other)
{
    (void)b;
    (void)other;
}

float dynamiccollisionbody_get_max_backup_time(CollisionBody *b)
{
    return ((DynamicCollisionBody *)b)->BackupTime;
}

void dynamiccollisionbody_set_position(CollisionBody *b, bVector3 *p)
{
    bVector3 *to = body_get_position(b);

    *to = *p;
}

// ------------------------------------------------------------- the replay

// 0x001d6a98. A restore that reads nothing leaves the stack's byte in
// retail; the port's is 0.
void collisionbody_do_snapshot(CollisionBody *b, ReplaySnapshot *s)
{
    uint8_t bits = 0;

    if (s->RestoringSnapshotFlag) {
        ReplaySnapshot_MoveUChar(s, &bits, 1);
        b->CollisionsDisabled = (int8_t)(bits & 15);
        b->ActiveCollisionDetection = (int8_t)(bits >> 4);
    } else {
        bits = (uint8_t)((uint8_t)b->CollisionsDisabled
                         + ((uint8_t)b->ActiveCollisionDetection << 4));
        ReplaySnapshot_MoveUChar(s, &bits, 1);
    }
    ReplaySnapshot_VerifyShort(s, &b->ID, 2);
    ReplaySnapshot_VerifyChar(s, &b->Type, 1);
    ReplaySnapshot_VerifyChar(s, &b->Dynamic, 1);
}

// 0x001d8760.
void staticcollisionbody_do_snapshot(CollisionBody *b, ReplaySnapshot *s)
{
    collisionbody_do_snapshot(b, s);
}

// 0x001d8918.
void trackpolygoncollisionbody_do_snapshot(CollisionBody *b, ReplaySnapshot *s)
{
    ReplaySnapshot_BeginSection(s, b, "TrackPolygonCollisionBody");
    collisionbody_do_snapshot(b, s);
    ReplaySnapshot_VerifyVector2(s, &b->BBoxMin);
    ReplaySnapshot_VerifyVector2(s, &b->BBoxMax);
    ReplaySnapshot_EndSection(s);
}

// 0x001d7050. Four bMemSets, in the image's order: BackupTime, then the
// backup's rotation, position and velocity.
void dynamiccollisionbody_do_snapshot(CollisionBody *b, ReplaySnapshot *s)
{
    DynamicCollisionBody *d = (DynamicCollisionBody *)b;
    int32_t taking = s->TakingSnapshotFlag || s->RestoringSnapshotFlag;

    ReplaySnapshot_BeginSection(s, d, "DynamicCollisionBody");
    collisionbody_do_snapshot(b, s);
    ReplaySnapshot_MoveInt(s, &d->PhysicsMode, 1);
    if (taking)
        topology_clear_interest_bbox(d->pTC);
    ReplaySnapshot_VerifyFloat(s, &d->CylinderBaseHeight);
    ReplaySnapshot_VerifyFloat(s, &d->CylinderTopHeight);
    ReplaySnapshot_VerifyFloat(s, &d->CylinderRadius);
    ReplaySnapshot_VerifyVector3(s, &d->LocalBBMin);
    ReplaySnapshot_VerifyVector3(s, &d->LocalBBMax);
    if (s->TakingSnapshotFlag || s->RestoringSnapshotFlag) {
        d->BackupTime = 0.0f;
        memset(&d->BackupRotation, 0, sizeof d->BackupRotation);
        memset(&d->BackupPosition, 0, sizeof d->BackupPosition);
        memset(&d->BackupVelocity, 0, sizeof d->BackupVelocity);
    }
    ReplaySnapshot_EndSection(s);
}

// ------------------------------------------------------------- the tables

#define E(f) { 0, 0, (VtFn)(f) }
#define PURE { 0, 0, NULL }

// _vt$13CollisionBody (0x0029bf48).
static const VtEntry collisionbody_vt[COLLISIONBODY_VT_ENTRIES] = {
    PURE,
    E(collisionbody_destroy),
    E(collisionbody_do_snapshot),
    PURE, PURE, PURE, PURE, PURE, PURE, PURE, PURE, // 24 .. 80
    PURE, PURE, PURE, PURE, PURE, PURE, PURE, PURE, // 88 .. 144
    PURE, PURE, PURE, PURE,                         // 152 .. 176
    E(collisionbody_is_blinking),                   // 184
    PURE, PURE,                                     // 192, 200
};

// _vt$19StaticCollisionBody (0x0029be78) and
// _vt$25TrackPolygonCollisionBody (0x0029bda8).
#define STATIC_SLOTS(dtor, snapshot, getpos, terrain)               \
    PURE,                                                           \
    E(dtor),                                                        \
    E(snapshot),                                                    \
    getpos,                                                         \
    E(staticcollisionbody_get_velocity),                            \
    E(staticcollisionbody_get_rotation),                            \
    E(staticcollisionbody_set_position),                            \
    E(staticcollisionbody_get_max_backup_time),                     \
    E(staticcollisionbody_move),                                    \
    E(staticcollisionbody_backup),                                  \
    E(staticcollisionbody_interpolate),                             \
    E(staticcollisionbody_recompute_auxilliaries),                  \
    E(staticcollisionbody_get_current_velocities),                  \
    E(staticcollisionbody_get_test_impulse_velocities),             \
    E(staticcollisionbody_set_to_physics_mode),                     \
    E(staticcollisionbody_consider_impulse),                        \
    E(staticcollisionbody_apply_impulse),                           \
    E(staticcollisionbody_are_collisions_enabled),                  \
    terrain,                                                        \
    E(staticcollisionbody_get_mass_inverse),                        \
    E(staticcollisionbody_get_inertia_tensor_inverse),              \
    E(staticcollisionbody_is_moveable),                             \
    E(staticcollisionbody_change_in_energy),                        \
    E(collisionbody_is_blinking),                                   \
    E(staticcollisionbody_get_bounciness),                          \
    E(staticcollisionbody_get_friction)

static const VtEntry staticcollisionbody_vt[COLLISIONBODY_VT_ENTRIES] = {
    STATIC_SLOTS(staticcollisionbody_destroy, staticcollisionbody_do_snapshot,
                 PURE, PURE)
};

static const VtEntry
trackpolygoncollisionbody_vt[COLLISIONBODY_VT_ENTRIES] = {
    STATIC_SLOTS(trackpolygoncollisionbody_destroy,
                 trackpolygoncollisionbody_do_snapshot,
                 E(trackpolygoncollisionbody_get_position),
                 E(trackpolygoncollisionbody_get_terrain_type))
};

// _vt$20DynamicCollisionBody (0x0029bcd8).
static const VtEntry dynamiccollisionbody_vt[COLLISIONBODY_VT_ENTRIES] = {
    PURE,
    E(dynamiccollisionbody_destroy),
    E(dynamiccollisionbody_do_snapshot),
    PURE, PURE, PURE,                               // 24, 32, 40
    E(dynamiccollisionbody_set_position),
    E(dynamiccollisionbody_get_max_backup_time),
    PURE,                                           // Move
    E(dynamiccollisionbody_backup),
    E(dynamiccollisionbody_interpolate),
    E(dynamiccollisionbody_recompute_auxilliaries),
    E(dynamiccollisionbody_get_current_velocities),
    E(dynamiccollisionbody_get_test_impulse_velocities),
    E(dynamiccollisionbody_set_to_physics_mode),
    PURE,                                           // ConsiderImpulse
    E(dynamiccollisionbody_apply_impulse),
    PURE, PURE,                                     // 136, 144
    E(dynamiccollisionbody_get_mass_inverse),
    E(dynamiccollisionbody_get_inertia_tensor_inverse),
    PURE,                                           // IsMoveable
    E(dynamiccollisionbody_change_in_energy),
    E(collisionbody_is_blinking),
    PURE, PURE,                                     // 192, 200
};

void collisionbody_install_vtables(void)
{
    vt_install(COLLISIONBODY_VTABLE, collisionbody_vt,
               COLLISIONBODY_VT_ENTRIES);
    vt_install(STATICCOLLISIONBODY_VTABLE, staticcollisionbody_vt,
               COLLISIONBODY_VT_ENTRIES);
    vt_install(TRACKPOLYGONCOLLISIONBODY_VTABLE, trackpolygoncollisionbody_vt,
               COLLISIONBODY_VT_ENTRIES);
    vt_install(DYNAMICCOLLISIONBODY_VTABLE, dynamiccollisionbody_vt,
               COLLISIONBODY_VT_ENTRIES);
}
