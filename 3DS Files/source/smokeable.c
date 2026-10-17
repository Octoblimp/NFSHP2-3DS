// smokeable -- see smokeable.h.

#include "smokeable.h"

#include <math.h>
#include <stdint.h>
#include <string.h>

#include "acidsys.h"
#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "bplist.h"
#include "bprintf.h"
#include "collision.h"
#include "collisionsound.h"
#include "eefpu.h"
#include "emath.h"
#include "physcomp.h"
#include "polyhedra.h"
#include "race.h"
#include "realtime.h"
#include "vclip.h"
#include "vtable.h"
#include "world.h"

SmokeableCreatorFn SmokeableCreators[ST_NUM_SMOKEABLE_TYPES];
BSlotPool  *VirginSmokeableSlotPool;
BSlotPool  *SmokeableSlotPool;
int32_t     AwakeSmokeablesCount;

// The .sdata floats at gp-15840, gp-15836 and gp-15832: the air drag's
// coefficient, the longest step Move integrates in one go, and how fast
// a loose smokeable's GroundRaise sinks back, per second.
static const float SmokeableAirDragCoefficient = 0.01f;
static const float SmokeableMaxTimeStep        = 0.01f;
static const float SmokeableGroundRaiseDecay   = 0.5f;

#define BODY_END ((CollisionBody *)(void *)&CollisionBodyList)

typedef void      (*VtDestroyFn)(void *self, int32_t flags);
typedef bVector3 *(*VtVectorFn)(void *self);
typedef bMatrix4 *(*VtMatrixFn)(void *self);
typedef int32_t   (*VtIntFn)(void *self);
typedef void      (*VtVoidFn)(void *self);
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

static bMatrix4 *body_rotation(void *b)
{
    const VtEntry *e = vt_slot(((CollisionBody *)b)->_vtable,
                               COLLISIONBODY_VT_GET_ROTATION);

    return ((VtMatrixFn)e->fn)(vt_this(b, e));
}

static int32_t body_int(void *b, int slot)
{
    const VtEntry *e = vt_slot(((CollisionBody *)b)->_vtable, slot);

    return ((VtIntFn)e->fn)(vt_this(b, e));
}

static RigidBody *rigid_body(const Smokeable *s)
{
    return (RigidBody *)s->Dynamic.pBody;
}

// `(float)(int)(WorldTimer - t) * 0.00025f`: a timer's age in seconds.
static float seconds_since(const Timer *t)
{
    return (float)(int32_t)((uint32_t)WorldTimer - t->PackedTime)
           * 0.00025f;
}

// The VU's length: the squares summed x, y, then z.
static float length3(float x, float y, float z)
{
    return sqrtf((x * x + y * y) + z * z);
}

static float min_s(float fs, float ft)
{
    return ft < fs ? ft : fs;
}

static float max_s(float fs, float ft)
{
    return fs < ft ? ft : fs;
}

// Padding2 is read as a word.
static int32_t info_pinned(const SmokeableInfo *si)
{
    uint32_t w;

    memcpy(&w, &si->Padding2, 4);
    return w != 0;
}

// The scenery instance's rotation, three rows in units of 2^-14, w 0.
static void instance_rotation(bMatrix4 *m, const SceneryInstance *inst)
{
    const float k = 1.0f / 16384.0f;
    bVector4   *row[3];
    int32_t     i;

    row[0] = &m->v0;
    row[1] = &m->v1;
    row[2] = &m->v2;
    for (i = 0; i < 3; i++) {
        row[i]->x = (float)inst->Rotation[3 * i] * k;
        row[i]->y = (float)inst->Rotation[3 * i + 1] * k;
        row[i]->z = (float)inst->Rotation[3 * i + 2] * k;
        row[i]->w = 0.0f;
    }
}

static AcidEmitter *node_emitter(const bNode *n)
{
    return (AcidEmitter *)((const bPNode *)(const void *)n)->Object;
}

// ------------------------------------------------------------ the module

void smokeable_register_creator(int32_t type, SmokeableCreatorFn fn)
{
    SmokeableCreators[type] = fn;
}

Smokeable *smokeable_create(int32_t type, int32_t id, SmokeableInfo *info,
                            uint32_t name_hash)
{
    return SmokeableCreators[type](id, info, name_hash);
}

Smokeable *smokeable_basic_creator(int32_t id, SmokeableInfo *info,
                                   uint32_t name_hash)
{
    return smokeable_init((Smokeable *)bSlotOMalloc(SmokeableSlotPool), id,
                          info, name_hash);
}

// The cross products are the VU's: A x N, then (A x N) x N. Their w lanes
// carry A's, which the image leaves as the stack had it; both are zeroed
// in the matrix.
int32_t smokeable_spawn(int32_t type, SmokeableInfo *info, uint32_t name_hash,
                        const bVector3 *pos, uint16_t ang)
{
    TopologyCoordinate tc;
    bVector3   n, a, b, c;
    bMatrix4   m;
    Smokeable *s;
    int32_t    found, id;
    float      elev, z;

    topology_init(&tc);
    elev = topology_get_elevation(&tc, pos, NULL, &n, &found);
    if (found == 0 || bIsSlotPoolFull(SmokeableSlotPool)) {
        topology_destroy(&tc);
        return -1;
    }
    id = (int16_t)collisionbody_get_next_id();
    s = smokeable_create(type, id, info, name_hash);
    z = (-s->Dynamic.LocalBBMin.z - s->SI->CenterOfMass[2]) * n.z;
    a.x = bCosBam(ang);
    a.y = bSinBam(ang);
    a.z = 0.0f;
    a.pad = 0.0f;
    z = elev + z;
    b.x = a.y * n.z - n.y * a.z;
    b.y = a.z * n.x - n.z * a.x;
    b.z = a.x * n.y - n.x * a.y;
    b.pad = a.pad;
    z = z + 0.06f;
    c.x = b.y * n.z - n.y * b.z;
    c.y = b.z * n.x - n.z * b.x;
    c.z = b.x * n.y - n.x * b.y;
    m.v0.x = c.x;
    m.v0.y = c.y;
    m.v0.z = c.z;
    m.v0.w = 0.0f;
    m.v1.x = b.x;
    m.v1.y = b.y;
    m.v1.z = b.z;
    m.v1.w = 0.0f;
    m.v2.x = n.x;
    m.v2.y = n.y;
    m.v2.z = n.z;
    m.v2.w = 0.0f;
    m.v3.x = pos->x;
    m.v3.y = pos->y;
    m.v3.z = z;
    m.v3.w = 1.0f;
    smokeable_set_initial_position(s, &m, NULL);
    topology_destroy(&tc);
    return id;
}

int32_t smokeable_spawn_matrix(int32_t type, SmokeableInfo *info,
                               uint32_t name_hash, const bMatrix4 *m)
{
    Smokeable *s;
    int32_t    id;

    if (bIsSlotPoolFull(SmokeableSlotPool))
        return -1;
    id = (int16_t)collisionbody_get_next_id();
    s = smokeable_create(type, id, info, name_hash);
    smokeable_set_initial_position(s, m, NULL);
    return id;
}

// The image reads the body's Type before its NULL test; a body that is
// gone reads low memory there. The port tests for NULL first.
void smokeable_delete(int32_t id, SmokeableInfo *info)
{
    CollisionBody *b;

    if ((int16_t)id < 0)
        return;
    b = collisionbody_find((int16_t)id);
    if (b == NULL || b->Type != 1
        || ((Smokeable *)(void *)b)->SI != info)
        return;
    body_destroy(b, 3);
}

// The position is loaded and stored back unchanged; only the rotation
// is rewritten, each element truncated by cvt.w.s.
void init_smokeables(void)
{
    int32_t i;

    for (i = 0; i < NumSmokeableSpawners; i++) {
        const SmokeableSpawner *sp = &pSmokeableSpawners[i];
        ScenerySectionHeader   *h =
            ScenerySectionHeaderTable[sp->ScenerySectionNumber];
        SceneryInstance *inst;
        bMatrix4         m;

        if (h == NULL)
            continue;
        inst = &h->pSceneryInstance[sp->SceneryInstanceNumber];
        instance_rotation(&m, inst);
        eOrthonormalizeMatrix(&m, &m);
        inst->Rotation[0] = (int16_t)ee_trunc_w(m.v0.x * 16384.0f);
        inst->Rotation[1] = (int16_t)ee_trunc_w(m.v0.y * 16384.0f);
        inst->Rotation[2] = (int16_t)ee_trunc_w(m.v0.z * 16384.0f);
        inst->Rotation[3] = (int16_t)ee_trunc_w(m.v1.x * 16384.0f);
        inst->Rotation[4] = (int16_t)ee_trunc_w(m.v1.y * 16384.0f);
        inst->Rotation[5] = (int16_t)ee_trunc_w(m.v1.z * 16384.0f);
        inst->Rotation[6] = (int16_t)ee_trunc_w(m.v2.x * 16384.0f);
        inst->Rotation[7] = (int16_t)ee_trunc_w(m.v2.y * 16384.0f);
        inst->Rotation[8] = (int16_t)ee_trunc_w(m.v2.z * 16384.0f);
    }
}

void close_smokeables(void)
{
}

// The list's head on the stack is a whole CollisionBody, as the image's
// bTList<CollisionBody> is reached: through the bodies' own links. A bare
// CollisionBodyNode written through them is, to GCC's strict aliasing at
// -O3, never written, and the loop that empties the list went: every
// smokeable and virgin stayed alive, off the body list, its WorldObject
// still on WorldObjectList, after its pool was freed (Restart Race's
// world went round a NULL node, TASKS 37f-2). The Makefile's
// -fno-strict-aliasing covers CollisionBodyList, reached the same way.
//
// A body moved from CollisionBodyList to the tail of `list`.
static void move_to_list(CollisionBody *list, CollisionBody *b)
{
    CollisionBody *next = b->Link.next, *prev = b->Link.prev;
    CollisionBody *tail;

    prev->Link.next = next;
    next->Link.prev = prev;
    tail = list->Link.prev;
    tail->Link.next = b;
    list->Link.prev = b;
    b->Link.prev = tail;
    b->Link.next = list;
}

// Each body on `list` back to the head of CollisionBodyList, and then
// destroyed with 3 (which takes it off again).
static void destroy_list(CollisionBody *list)
{
    while (list->Link.next != list) {
        CollisionBody *b = list->Link.next;
        CollisionBody *next = b->Link.next, *prev = b->Link.prev;
        CollisionBody *head;

        prev->Link.next = next;
        next->Link.prev = prev;
        head = CollisionBodyList.next;
        CollisionBodyList.next = b;
        head->Link.prev = b;
        b->Link.next = head;
        b->Link.prev = BODY_END;
        body_destroy(b, 3);
    }
}

void delete_smokeable_collision_bodies(void)
{
    CollisionBody  list;
    CollisionBody *b, *next;

    list.Link.next = &list;
    list.Link.prev = &list;
    for (b = CollisionBodyList.next; b != BODY_END; b = next) {
        next = b->Link.next;
        if (b->Type == 2 || b->Type == 1)
            move_to_list(&list, b);
    }
    destroy_list(&list);
}

void delete_far_away_smokeable_collision_bodies(void)
{
    CollisionBody  list;
    CollisionBody *b, *next;

    if (SmokeableSlotPool == NULL)
        return;
    list.Link.next = &list;
    list.Link.prev = &list;
    for (b = CollisionBodyList.next; b != BODY_END; b = next) {
        const bVector3 *v;

        next = b->Link.next;
        if (b->Type != 1)
            continue;
        v = body_vector(b, COLLISIONBODY_VT_GET_VELOCITY);
        if (1000.0f < length3(v->x, v->y, v->z)
            && !info_pinned(((Smokeable *)(void *)b)->SI))
            move_to_list(&list, b);
        if (50.0f < fabsf(body_rotation(b)->v0.x))
            move_to_list(&list, b);
    }
    if (bCountFreeSlots(SmokeableSlotPool) < 10) {
        for (b = CollisionBodyList.next; b != BODY_END; b = next) {
            Smokeable *s = (Smokeable *)(void *)b;
            float      d, t;

            next = b->Link.next;
            if (b->Type != 1)
                continue;
            d = world_get_distance_to_closest_player(
                pCurrentWorld, body_vector(b, COLLISIONBODY_VT_GET_POSITION));
            if (s->Awake != 0)
                continue;
            t = timer_is_valid(&s->TimeAwoken) ? seconds_since(&s->TimeAwoken)
                                               : 0.0f;
            if (45.0f < t && 120.0f < d && !info_pinned(s->SI))
                move_to_list(&list, b);
        }
    }
    destroy_list(&list);
}

void spawn_smokeables(void)
{
    bNode  *n;
    int32_t i;

    for (n = SmokeableInfoList.next; n != &SmokeableInfoList; n = n->next) {
        SmokeableInfo *si = (SmokeableInfo *)(void *)n;

        afx_get_emitters(&si->AnchorEmitterList,
                         si->AnchorEmitterGroupNameHash);
        afx_get_emitters(&si->DynamicEmitterList,
                         si->DynamicEmitterGroupNameHash);
    }
    VirginSmokeableSlotPool = bNewSlotPool((int)sizeof(VirginSmokeable),
                                           NumSmokeableSpawners,
                                           "VirginSmokeableSlotPool", 16);
    SmokeableSlotPool = bNewSlotPool((int)sizeof(Smokeable), 32,
                                     "SmokeableSlotPool", 16);
    smokeable_register_creator(ST_BASIC_SMOKEABLE, smokeable_basic_creator);
    for (i = 0; i < NumSmokeableSpawners; i++) {
        SmokeableSpawner     *sp = &pSmokeableSpawners[i];
        ScenerySectionHeader *h =
            ScenerySectionHeaderTable[sp->ScenerySectionNumber];
        const SceneryInstance *inst;

        if (h == NULL)
            continue;
        inst = &h->pSceneryInstance[sp->SceneryInstanceNumber];
        if (TheRaceParameters.NumPlayerCars == 2
            && (inst->ExcludeFlags & 1) != 0)
            continue;
        if (find_smokeable_info(sp->SmokeableInfoHash) == NULL)
            continue;
        virginsmokeable_init(
            (VirginSmokeable *)bSlotOMalloc(VirginSmokeableSlotPool), sp);
    }
}

void clear_smokeables(void)
{
    bNode *n;

    delete_smokeable_collision_bodies();
    if (VirginSmokeableSlotPool != NULL) {
        bDeleteSlotPool(VirginSmokeableSlotPool);
        VirginSmokeableSlotPool = NULL;
    }
    if (SmokeableSlotPool != NULL) {
        bDeleteSlotPool(SmokeableSlotPool);
        SmokeableSlotPool = NULL;
    }
    for (n = SmokeableInfoList.next; n != &SmokeableInfoList; n = n->next) {
        SmokeableInfo *si = (SmokeableInfo *)(void *)n;

        afx_delete_emitters(&si->AnchorEmitterList);
        afx_delete_emitters(&si->DynamicEmitterList);
    }
}

CollisionBody *smokeable_convert_body(CollisionBody *b)
{
    Smokeable *s = virginsmokeable_convert((VirginSmokeable *)(void *)b);

    if (b != NULL)
        body_destroy(b, 3);
    return (CollisionBody *)(void *)s;
}

// ------------------------------------------------------ VirginSmokeable

// The image's bSPrintf has no bound; the name is at most 15 + 23.
VirginSmokeable *virginsmokeable_init(VirginSmokeable *v,
                                      SmokeableSpawner *spawner)
{
    CollisionStats       *cs = &TheCollisionStats;
    ScenerySectionHeader *h;
    SceneryInstance      *inst;
    char                  name[48];
    bVector2              mn, mx;
    bMatrix4              m;

    staticcollisionbody_init(&v->Static,
                             ~(int32_t)(spawner - pSmokeableSpawners), 2);
    v->Static.Body._vtable = VIRGINSMOKEABLE_VTABLE;
    cs->NumVirginSmokeableCollisionBodies++;
    if (cs->HighestNumVirginSmokeableCollisionBodies
        < cs->NumVirginSmokeableCollisionBodies)
        cs->HighestNumVirginSmokeableCollisionBodies =
            cs->NumVirginSmokeableCollisionBodies;
    v->pSmokeableSpawner = spawner;
    h = ScenerySectionHeaderTable[spawner->ScenerySectionNumber];
    v->pSmokeableInfo = find_smokeable_info(spawner->SmokeableInfoHash);
    inst = &h->pSceneryInstance[spawner->SceneryInstanceNumber];
    v->pSceneryInstance = inst;
    inst->ExcludeFlags &= 0xffef;
    v->pSceneryInfo = &h->pSceneryInfo[inst->SceneryInfoNumber];
    b_snprintf(name, sizeof name, "VirginSmokeable%s",
               v->pSmokeableInfo->Name);
    collisionbody_set_debug_name(&v->Static.Body, name);
    v->Static.Body.pPoly = NULL;
    v->Static.Body.CollisionsDisabled = 0;
    v->Static.Body.ActiveCollisionDetection = 0;
    mn.x = (float)inst->BBox.BBoxMin[0];
    mn.y = (float)inst->BBox.BBoxMin[1];
    mx.x = (float)inst->BBox.BBoxMax[0];
    mx.y = (float)inst->BBox.BBoxMax[1];
    collisionbody_set_bbox_min_max(&v->Static.Body, &mn, &mx);
    bIdentity(&m);
    collisionbody_plot_to_caffeine(
        &v->Static.Body, &m, (const bVector3 *)(const void *)inst->Position);
    return v;
}

void virginsmokeable_destroy(VirginSmokeable *v, int32_t flags)
{
    v->Static.Body._vtable = VIRGINSMOKEABLE_VTABLE;
    TheCollisionStats.NumVirginSmokeableCollisionBodies--;
    v->pSceneryInstance->ExcludeFlags |= 0x10;
    staticcollisionbody_destroy(&v->Static, 0);
    if (flags & 1)
        bSlotFree(VirginSmokeableSlotPool, v);
}

// The new body's id is GetNextCollisionBodyID's int, not cut to sixteen
// bits as Spawn's is.
Smokeable *virginsmokeable_convert(VirginSmokeable *v)
{
    const SceneryInstance *inst;
    Smokeable             *s;
    bMatrix4               m;

    if (bIsSlotPoolFull(SmokeableSlotPool))
        return NULL;
    inst = v->pSceneryInstance;
    instance_rotation(&m, inst);
    m.v3.x = inst->Position[0];
    m.v3.y = inst->Position[1];
    m.v3.z = inst->Position[2];
    m.v3.w = 1.0f;
    s = smokeable_create(ST_BASIC_SMOKEABLE, collisionbody_get_next_id(),
                         v->pSmokeableInfo, v->pSceneryInfo->NameHash[0]);
    if (body_int(s, SMOKEABLE_VT_GET_SMOKE_TYPE) == 0) {
        TopologyCoordinate tc;
        bVector3           n;
        int32_t            found;
        float              elev, raise;

        topology_init(&tc);
        elev = topology_get_elevation(
            &tc, (const bVector3 *)(const void *)&m.v3, NULL, &n, &found);
        if (found != 0) {
            raise = (elev - (m.v3.z + (s->Dynamic.LocalBBMin.z
                                       + s->SI->CenterOfMass[2]) * n.z))
                    + 0.05f;
            if (0.0f < raise) {
                s->GroundRaise = raise;
                m.v3.z = m.v3.z + raise;
            }
        }
        topology_destroy(&tc);
    }
    s->pSmokeableSpawner = v->pSmokeableSpawner;
    smokeable_set_initial_position(s, &m, NULL);
    return s;
}

bVector3 *virginsmokeable_get_position(CollisionBody *b)
{
    (void)b;
    return &ZeroVector;
}

int32_t virginsmokeable_get_terrain_type(CollisionBody *b)
{
    return ((VirginSmokeable *)(void *)b)->pSmokeableInfo->TheTerrainType;
}

// ------------------------------------------------------------ Smokeable

// Each of the info's emitters copied, set going, and pushed on the head
// of `list` -- so the copies are in the opposite order. The info is read
// again for each.
static void copy_emitters(Smokeable *s, bNode *list, int dynamic)
{
    bNode *e;

    for (e = dynamic ? s->SI->DynamicEmitterList.next
                     : s->SI->AnchorEmitterList.next;
         e != (dynamic ? &s->SI->DynamicEmitterList
                       : &s->SI->AnchorEmitterList);
         e = e->next) {
        AcidEmitter *c = afx_copy_emitter((const AcidEmitter *)(void *)e);
        bPNode      *node;
        bNode       *head;

        if (c == NULL)
            continue;
        c->State = 1;
        node = bpnode_malloc();
        head = list->next;
        list->next = &node->Node;
        head->prev = &node->Node;
        node->Node.next = head;
        node->Object = c;
        node->Node.prev = list;
    }
}

Smokeable *smokeable_init(Smokeable *s, int32_t id, SmokeableInfo *info,
                          uint32_t name_hash)
{
    CollisionStats     *cs = &TheCollisionStats;
    PipelinePolyhedron *pp;
    RigidBody          *rb;
    char                name[48];

    dynamiccollisionbody_init(&s->Dynamic, id, 1, &s->TC);
    physicssystem_init(&s->System);
    s->TimeCreated.PackedTime = 0;
    s->TimeAwoken.PackedTime = 0;
    s->TimeLastCarContact.PackedTime = 0;
    s->System._vtable = SMOKEABLE_SYSTEM_VTABLE;
    topology_init(&s->TC);
    s->Dynamic.Body._vtable = SMOKEABLE_VTABLE;
    worldobject_construct(&s->TheWorldObject, name_hash, NULL, 0);
    s->AnchorEmitterList.next = &s->AnchorEmitterList;
    s->AnchorEmitterList.prev = &s->AnchorEmitterList;
    s->DynamicEmitterList.next = &s->DynamicEmitterList;
    s->DynamicEmitterList.prev = &s->DynamicEmitterList;
    cs->NumSmokeableCollisionBodies++;
    if (cs->HighestNumSmokeableCollisionBodies
        < cs->NumSmokeableCollisionBodies)
        cs->HighestNumSmokeableCollisionBodies =
            cs->NumSmokeableCollisionBodies;
    rb = rigidbody_init((RigidBody *)bSlotOMalloc(RigidBodySlotPool),
                        &info->RBI);
    s->Dynamic.Body.CollisionsDisabled = 0;
    s->Dynamic.PhysicsMode = 1;
    s->Dynamic.Body.ActiveCollisionDetection = 0;
    s->Dynamic.pSystem = &s->System;
    s->TimeAwoken.PackedTime = 0;
    s->TimeLastCarContact.PackedTime = 0;
    s->Dynamic.pBody = rb;
    s->TimeCreated.PackedTime = (uint32_t)WorldTimer;
    b_snprintf(name, sizeof name, "Smokeable%s", info->Name);
    collisionbody_set_debug_name(&s->Dynamic.Body, name);
    pp = find_pipeline_polyhedron(info->NameHash,
                                  (bVector3 *)(void *)info->CenterOfMass);
    if (pp != NULL)
        s->Dynamic.Body.pPoly = (VCPolyhedron *)(void *)pp;
    else
        s->Dynamic.Body.pPoly = (VCPolyhedron *)(void *)rectpoly_init(
            (RectPolyhedron *)bMalloc((int)sizeof(RectPolyhedron),
                                      "RectPolyhedron", 0, 16),
            1.5f, -1.5f, 1.5f, -1.5f, 1.5f, -1.5f);
    dynamiccollisionbody_build_bounding_volumes(&s->Dynamic);
    physicssystem_add_component(&s->System,
                                (PhysicsComponent *)(void *)rb);
    s->Awake = 0;
    s->Blinking = 0;
    s->SI = info;
    s->AnchorStrength = info->AnchorStrength;
    s->pSmokeableSpawner = NULL;
    s->GroundRaise = 0.0f;
    s->BreakingStrength = info->BreakingStrength;
    if (!smokeable_does_child_art_exist(s))
        s->BreakingStrength = 0.0f;
    smokeable_calibrate(s);
    s->AnchorEmittersAdded = 0;
    s->DynamicEmittersAdded = 0;
    if (info->AnchorEmitterGroupNameHash != 0)
        copy_emitters(s, &s->AnchorEmitterList, 0);
    if (info->DynamicEmitterGroupNameHash != 0)
        copy_emitters(s, &s->DynamicEmitterList, 1);
    return s;
}

// RemoveHead, then the emitter off the effects system when it was added
// (whether or not the node held one) and destroyed.
static void drain_emitters(Smokeable *s, bNode *list, const int8_t *added)
{
    while (list->next != list) {
        bPNode      *node = (bPNode *)(void *)list->next;
        AcidEmitter *e = (AcidEmitter *)node->Object;
        bNode       *next = node->Node.next, *prev = node->Node.prev;

        prev->next = next;
        next->prev = prev;
        bpnode_free(node);
        if (*added != 0)
            acid_system_remove_auto_emitter(&WorldEffects, e);
        if (e != NULL)
            acid_emitter_delete(e, 3);
    }
    (void)s;
}

void smokeable_destroy(Smokeable *s, int32_t flags)
{
    s->System._vtable = SMOKEABLE_SYSTEM_VTABLE;
    TheCollisionStats.NumSmokeableCollisionBodies--;
    s->Dynamic.Body._vtable = SMOKEABLE_VTABLE;
    if (find_pipeline_polyhedron(s->SI->NameHash, NULL) == NULL
        && s->Dynamic.Body.pPoly != NULL)
        vcpoly_destroy(s->Dynamic.Body.pPoly, 3);
    drain_emitters(s, &s->AnchorEmitterList, &s->AnchorEmittersAdded);
    drain_emitters(s, &s->DynamicEmitterList, &s->DynamicEmittersAdded);
    worldobject_destruct(&s->TheWorldObject, 2);
    topology_destroy(&s->TC);
    physicssystem_fini(&s->System, 0);
    dynamiccollisionbody_destroy(&s->Dynamic, 0);
    if (flags & 1)
        bSlotFree(SmokeableSlotPool, s);
}

// The momentum is (0, 0, 0, 1), or the velocity times the mass on all
// four lanes; the angular momentum's w is the stack's in the image, 0
// here. The backup is the state as set.
void smokeable_set_initial_position(Smokeable *s, const bMatrix4 *m,
                                    const bVector3 *vel)
{
    RigidBody     *rb = rigid_body(s);
    bVector4       pos, p, l;
    bMatrix4       r, w;
    bVector3       t;
    bNode         *n;
    const VtEntry *e;

    pos = m->v3;
    r = *m;
    r.v3.x = 0.0f;
    r.v3.y = 0.0f;
    r.v3.z = 0.0f;
    r.v3.w = 1.0f;
    l.x = 0.0f;
    l.y = 0.0f;
    l.z = 0.0f;
    l.w = 0.0f;
    p.x = 0.0f;
    p.y = 0.0f;
    p.z = 0.0f;
    p.w = 1.0f;
    if (vel != NULL) {
        float mass = rb->Mass;

        p.x = vel->x * mass;
        p.y = vel->y * mass;
        p.z = vel->z * mass;
        p.w = vel->pad * mass;
    }
    bMulMatrixVec3(&t, &r, (const bVector3 *)(const void *)s->SI->CenterOfMass);
    pos.x = pos.x + t.x;
    pos.y = pos.y + t.y;
    pos.z = pos.z + t.z;
    pos.w = pos.w + t.pad;
    rigidbody_set_state(rb, &pos, &r, &p, &l);
    w = *m;
    w.v3.z = w.v3.z - s->GroundRaise;
    s->TheWorldObject.Matrix = w;
    s->TheWorldObject.Enabled = 1;
    s->Dynamic.BackupPosition.x = pos.x;
    s->Dynamic.BackupPosition.y = pos.y;
    s->Dynamic.BackupPosition.z = pos.z;
    s->Dynamic.BackupPosition.pad = pos.w;
    s->Dynamic.BackupRotation = r;
    s->Dynamic.BackupVelocity.x = l.x;
    s->Dynamic.BackupVelocity.y = l.y;
    s->Dynamic.BackupVelocity.z = l.z;
    s->Dynamic.BackupVelocity.pad = l.w;
    s->Dynamic.BackupTime = 5000.0f;
    e = vt_slot(s->System._vtable, PHYSICSSYSTEM_VT_COMPUTE_AUXILIARIES);
    ((VtVoidFn)e->fn)(vt_this(&s->System, e));
    dynamiccollisionbody_update_position(&s->Dynamic);
    for (n = s->AnchorEmitterList.next; n != &s->AnchorEmitterList;
         n = n->next)
        node_emitter(n)->LocalWorld = *m;
    for (n = s->DynamicEmitterList.next; n != &s->DynamicEmitterList;
         n = n->next)
        node_emitter(n)->LocalWorld = *m;
}

void smokeable_calibrate(Smokeable *s)
{
    rigidbody_calibrate(rigid_body(s), NULL);
    rigidbody_calculate_inertia_tensor(rigid_body(s));
}

// 0x00220c80, unnamed: drag against the velocity, k |v| v with k the
// coefficient, at the centre. The point's w is the stack's in the image.
static void smokeable_air_drag(RigidBody *rb)
{
    bVector4 v = rb->Velocity, f, at;
    float    k = -length3(v.x, v.y, v.z) * SmokeableAirDragCoefficient;

    f.x = v.x * k;
    f.y = v.y * k;
    f.z = v.z * k;
    f.w = v.w * k;
    at.x = 0.0f;
    at.y = 0.0f;
    at.z = 0.0f;
    at.w = 0.0f;
    rigidbody_apply_force(rb, &f, &at);
}

// Two models drag through the air: retail's hashes 0x98c6023c and
// 0x8ac70e76.
#define SMOKEABLE_DRAG_HASH_A 0x98c6023cu
#define SMOKEABLE_DRAG_HASH_B 0x8ac70e76u

void smokeable_move(CollisionBody *b, float dt)
{
    Smokeable *s = (Smokeable *)(void *)b;
    RigidBody *rb;
    bVector3   t;
    bMatrix4   m;

    dynamiccollisionbody_begin_move(&s->Dynamic, dt);
    if (s->Awake != 0) {
        int32_t drag = 0, n, i;
        float   h;

        smokeable_calibrate(s);
        rigid_body(s)->MotionDamping = 1;
        if (worldobject_get_name_hash(&s->TheWorldObject)
                == SMOKEABLE_DRAG_HASH_A
            || worldobject_get_name_hash(&s->TheWorldObject)
                   == SMOKEABLE_DRAG_HASH_B)
            drag = 1;
        n = ee_trunc_w(ee_div(dt, SmokeableMaxTimeStep)) + 1;
        h = ee_div(dt, (float)n);
        for (i = 0; i < n; i++) {
            if (drag)
                smokeable_air_drag(rigid_body(s));
            physicssystem_integrate_euler(&s->System, h);
            rb = rigid_body(s);
            eOrthonormalizeMatrix(&rb->State.R, &rb->State.R);
        }
        smokeable_consider_sleeping(s);
        smokeable_position_changed(s);
        if (smokeable_touching_car(s))
            s->TimeLastCarContact.PackedTime = (uint32_t)WorldTimer;
    }
    rb = rigid_body(s);
    bMulMatrixVec3(&t, &rb->State.R,
                   (const bVector3 *)(const void *)s->SI->CenterOfMass);
    m.v0 = rb->State.R.v0;
    m.v1 = rb->State.R.v1;
    m.v2 = rb->State.R.v2;
    m.v3.x = rb->State.X.x - t.x;
    m.v3.y = rb->State.X.y - t.y;
    m.v3.z = rb->State.X.z - t.z;
    m.v3.w = 1.0f;
    m.v3.z = m.v3.z - s->GroundRaise;
    if (body_int(s, COLLISIONBODY_VT_IS_BLINKING) != 0
        && (WorldLoopCounter & 1) == 0) {
        s->TheWorldObject.Enabled = 0;
    } else {
        s->TheWorldObject.Matrix = m;
        s->TheWorldObject.Enabled = 1;
    }
    m.v3.x = m.v3.x + t.x;
    m.v3.y = m.v3.y + t.y;
    m.v3.z = m.v3.z + t.z;
    m.v3.w = 1.0f;
    smokeable_service_emitters(s, &m);
    if (smokeable_check_timers(s))
        return;
    if (s->AnchorStrength == 0.0f) {
        float r = s->GroundRaise - dt * SmokeableGroundRaiseDecay;

        s->GroundRaise = r;
        if (r < 0.0f)
            s->GroundRaise = 0.0f;
    }
}

// The interest box: the smaller of the cylinder's base height and its
// radius, and a twentieth of the speed up to 6, about the position.
void smokeable_position_changed(Smokeable *s)
{
    float           r = min_s(s->Dynamic.CylinderBaseHeight,
                              s->Dynamic.CylinderRadius);
    const bVector3 *v = body_vector(s, COLLISIONBODY_VT_GET_VELOCITY);
    float           sp = min_s(length3(v->x, v->y, v->z) * 0.05f, 6.0f);
    const bVector3 *pos = body_vector(s, COLLISIONBODY_VT_GET_POSITION);

    r = r + sp;
    topology_set_interest_bbox3(&s->TC, pos, r,
                                body_vector(s, COLLISIONBODY_VT_GET_VELOCITY));
    dynamiccollisionbody_update_position(&s->Dynamic);
}

void smokeable_service_emitters(Smokeable *s, const bMatrix4 *m)
{
    const bVector3 *v;
    bNode          *n;

    if (s->Awake == 0)
        return;
    v = body_vector(s, COLLISIONBODY_VT_GET_VELOCITY);
    for (n = s->DynamicEmitterList.next; n != &s->DynamicEmitterList;
         n = n->next) {
        AcidEmitter *e = node_emitter(n);

        e->LocalWorld = *m;
        e->InheritVelocity.x = v->x;
        e->InheritVelocity.y = v->y;
        e->InheritVelocity.z = v->z;
        e->InheritVelocity.w = 0.0f;
    }
    if (s->AnchorEmittersAdded != 1)
        return;
    for (n = s->AnchorEmitterList.next; n != &s->AnchorEmitterList;
         n = n->next) {
        AcidEmitter *e = node_emitter(n);

        e->InheritVelocity.x = v->x;
        e->InheritVelocity.y = v->y;
        e->InheritVelocity.z = v->z;
        e->InheritVelocity.w = 0.0f;
    }
    s->AnchorEmittersAdded = 2;
}

int32_t smokeable_check_timers(Smokeable *s)
{
    if (s->pSmokeableSpawner != NULL && !timer_is_valid(&s->TimeAwoken)
        && s->Dynamic.Body.NumWitnesses == 0
        && 2.0f < seconds_since(&s->TimeCreated)) {
        virginsmokeable_init(
            (VirginSmokeable *)bSlotOMalloc(VirginSmokeableSlotPool),
            s->pSmokeableSpawner);
        body_destroy(s, 3);
        return 1;
    }
    if (timer_is_valid(&s->TimeAwoken) && s->SI->Lifetime != 0.0f
        && s->SI->Lifetime <= seconds_since(&s->TimeAwoken)) {
        const VtEntry *e = vt_slot(s->Dynamic.Body._vtable,
                                   SMOKEABLE_VT_ON_LIFETIME_END);

        ((VtVoidFn)e->fn)(vt_this(s, e));
        body_destroy(s, 3);
        return 1;
    }
    return 0;
}

void smokeable_activate_anchor_emitters(Smokeable *s)
{
    bNode *n;

    for (n = s->AnchorEmitterList.next; n != &s->AnchorEmitterList;
         n = n->next)
        acid_system_add_auto_emitter(&WorldEffects, node_emitter(n));
    s->AnchorEmittersAdded = 1;
}

// A sleeping smokeable still anchored is pulled loose only by an impulse
// whose size, or whose moment about the centre of mass, reaches the
// anchor's strength: then the part of it the anchor took is played back
// against the centre and the rest goes on. What reaches a breakable one
// wears its strength down by half of it, until one impulse is as large
// as what is left.
float smokeable_consider_impulse(CollisionBody *b, bVector3 *j, bVector3 *at)
{
    Smokeable *s = (Smokeable *)(void *)b;
    float      f = 1.0f, bs, sum;

    if (s->Awake == 0) {
        float as = s->AnchorStrength;

        if (as == 0.0f) {
            smokeable_awaken(s);
        } else {
            const SmokeableInfo *si = s->SI;
            bVector3             a, c, imp, pt;
            const VtEntry       *e;
            float                m;

            a.x = at->x + si->CenterOfMass[0];
            a.y = at->y + si->CenterOfMass[1];
            a.z = at->z + si->CenterOfMass[2];
            a.pad = at->pad + si->Padding;
            c.x = a.y * j->z - j->y * a.z;
            c.y = a.z * j->x - j->z * a.x;
            c.z = a.x * j->y - j->x * a.y;
            m = max_s(length3(c.x, c.y, c.z), length3(j->x, j->y, j->z));
            if (m < as)
                return 1.0f;
            f = ee_div(as, m);
            collision_sound_play_smokeable(
                body_vector(s, COLLISIONBODY_VT_GET_POSITION), s->SI);
            imp.x = j->x * -f;
            imp.y = j->y * -f;
            imp.z = j->z * -f;
            imp.pad = j->pad * -f;
            si = s->SI;
            pt.x = 0.0f - si->CenterOfMass[0];
            pt.y = 0.0f - si->CenterOfMass[1];
            pt.z = 0.0f - si->CenterOfMass[2];
            pt.pad = 1.0f - si->Padding;
            smokeable_awaken(s);
            s->AnchorStrength = 0.0f;
            e = vt_slot(s->Dynamic.Body._vtable,
                        COLLISIONBODY_VT_APPLY_IMPULSE);
            ((VtImpulseFn)e->fn)(vt_this(s, e), &imp, &pt);
            smokeable_activate_anchor_emitters(s);
        }
    }
    bs = s->BreakingStrength;
    if (bs == 0.0f)
        return f;
    sum = f * ((fabsf(j->x) + fabsf(j->y)) + fabsf(j->z));
    if (bs <= sum) {
        s->BreakingStrength = -1.0f;
        f = ee_div(-f * bs, sum);
    } else {
        s->BreakingStrength = bs - sum * 0.5f;
    }
    return f;
}

// Two seconds from the last car, a collision half a second old, and
// barely moving. The car's stamp is not tested for validity.
void smokeable_consider_sleeping(Smokeable *s)
{
    struct Collision *c;
    RigidBody        *rb;

    if (!(2.0f < seconds_since(&s->TimeLastCarContact)))
        return;
    if (s->Dynamic.Body.NumCollisions == 0)
        return;
    c = collisionbody_get_collision(&s->Dynamic.Body, 0);
    if (!(0.5f < seconds_since(&c->CollisionTime)))
        return;
    rb = rigid_body(s);
    if (!(length3(rb->Velocity.x, rb->Velocity.y, rb->Velocity.z) < 1.5f))
        return;
    if (!(length3(rb->AngularVelocity.x, rb->AngularVelocity.y,
                  rb->AngularVelocity.z) < 4.0f))
        return;
    smokeable_put_to_sleep(s);
}

void smokeable_put_to_sleep(Smokeable *s)
{
    s->Awake = 0;
    s->Dynamic.Body.ActiveCollisionDetection = 0;
    AwakeSmokeablesCount--;
    topology_clear_interest_bbox(&s->TC);
}

void smokeable_awaken(Smokeable *s)
{
    s->Dynamic.Body.ActiveCollisionDetection = 1;
    s->Awake = 1;
    AwakeSmokeablesCount++;
    if (s->DynamicEmittersAdded == 0) {
        bNode *n;

        for (n = s->DynamicEmitterList.next; n != &s->DynamicEmitterList;
             n = n->next)
            acid_system_add_auto_emitter(&WorldEffects, node_emitter(n));
        s->DynamicEmittersAdded = 1;
    }
    if (!timer_is_valid(&s->TimeAwoken))
        s->TimeAwoken.PackedTime = (uint32_t)WorldTimer;
}

// The pieces' models are this one's name followed by "_CHILD1" and on,
// hashed on from this model's hash.
int32_t smokeable_break(Smokeable *s, DynamicCollisionBody **pieces)
{
    char    name[8];
    int32_t n = s->SI->NumChildren, i;

    memcpy(name, "_CHILDx", 8);
    for (i = 0; i < n; i++) {
        int32_t    id = collisionbody_get_next_id();
        uint32_t   h;
        Smokeable *c;

        name[6] = (char)('1' + i);
        h = bchunk_hash_from(name,
                             worldobject_get_name_hash(&s->TheWorldObject));
        c = smokeable_create(ST_BASIC_SMOKEABLE, id, s->SI->pChildren[i], h);
        smokeable_set_initial_position(c, &s->TheWorldObject.Matrix, NULL);
        smokeable_awaken(c);
        pieces[i] = &c->Dynamic;
    }
    body_destroy(s, 3);
    return n;
}

int32_t smokeable_does_child_art_exist(Smokeable *s)
{
    char    name[8];
    int32_t n = s->SI->NumChildren, i;

    memcpy(name, "_CHILDx", 8);
    for (i = 0; i < n; i++) {
        name[6] = (char)('1' + i);
        if (!worldobject_does_art_exist(bchunk_hash_from(
                name, worldobject_get_name_hash(&s->TheWorldObject))))
            return 0;
    }
    return 1;
}

// 0x00221908, unnamed. 0 moving, 1 slowing, 2 settled: settled is under
// a quarter in both speeds, touching something, and two seconds from the
// last car.
static int32_t smokeable_motion_class(Smokeable *s)
{
    RigidBody *rb = rigid_body(s);
    float      v = length3(rb->Velocity.x, rb->Velocity.y, rb->Velocity.z);
    float      w = length3(rb->AngularVelocity.x, rb->AngularVelocity.y,
                           rb->AngularVelocity.z);

    if (0.7f < v || 0.7f < w)
        return 0;
    if (s->Dynamic.Body.NumCollisions == 0)
        return 0;
    if (0.25f < v || 0.25f < w)
        return 1;
    return 2.0f < seconds_since(&s->TimeLastCarContact) ? 1 : 2;
}

// 0x002219f8, the system table's slot 16: ComputeAuxiliaries, then the
// momenta damped by 0.95 for a slowing smokeable and stopped for a
// settled one, and the auxiliaries again after either. The stopped
// momenta's w lanes are the stack's in the image, 0 here.
void smokeable_system_compute_auxiliaries(void *self)
{
    Smokeable *s = (Smokeable *)self;
    RigidBody *rb;
    int32_t    changed = 0;

    physicssystem_compute_auxiliaries(&s->System);
    switch (smokeable_motion_class(s)) {
    case 1:
        changed = 1;
        rb = rigid_body(s);
        rb->State.P.x = rb->State.P.x * 0.95f;
        rb->State.P.y = rb->State.P.y * 0.95f;
        rb->State.P.z = rb->State.P.z * 0.95f;
        rb->State.P.w = rb->State.P.w * 0.95f;
        rb->State.L.x = rb->State.L.x * 0.95f;
        rb->State.L.y = rb->State.L.y * 0.95f;
        rb->State.L.z = rb->State.L.z * 0.95f;
        rb->State.L.w = rb->State.L.w * 0.95f;
        break;
    case 2:
        changed = 1;
        rb = rigid_body(s);
        rb->State.P.x = 0.0f;
        rb->State.P.y = 0.0f;
        rb->State.P.z = 0.0f;
        rb->State.P.w = 0.0f;
        rb->State.L = rb->State.P;
        break;
    default:
        break;
    }
    if (changed)
        physicssystem_compute_auxiliaries(&s->System);
}

int32_t smokeable_touching_car(Smokeable *s)
{
    int32_t n = s->Dynamic.Body.NumCollisions, i;

    for (i = 0; i < n; i++) {
        struct Car *c1, *c2;

        collision_get_colliding_cars(
            collisionbody_get_collision(&s->Dynamic.Body, i), &c1, &c2);
        if (c1 != NULL || c2 != NULL)
            return 1;
    }
    return 0;
}

void smokeable_set_ground_raise(Smokeable *s, float r)
{
    s->GroundRaise = r;
}

float smokeable_get_ground_raise(Smokeable *s)
{
    return s->GroundRaise;
}

TopologyCoordinate *smokeable_get_topology_coordinate(Smokeable *s)
{
    return &s->TC;
}

float smokeable_get_time_alive(Smokeable *s)
{
    if (!timer_is_valid(&s->TimeAwoken))
        return 0.0f;
    return seconds_since(&s->TimeAwoken);
}

void smokeable_set_blinking(Smokeable *s, int32_t on)
{
    s->Blinking = (int8_t)on;
}

// ------------------------------------------------------------ the table

bVector3 *smokeable_get_position(CollisionBody *b)
{
    return (bVector3 *)(void *)&rigid_body((Smokeable *)(void *)b)->State.X;
}

bVector3 *smokeable_get_velocity(CollisionBody *b)
{
    return (bVector3 *)(void *)&rigid_body((Smokeable *)(void *)b)->Velocity;
}

bMatrix4 *smokeable_get_rotation(CollisionBody *b)
{
    return &rigid_body((Smokeable *)(void *)b)->State.R;
}

void smokeable_apply_impulse(CollisionBody *b, bVector3 *j, bVector3 *at)
{
    Smokeable *s = (Smokeable *)(void *)b;

    if (s->Awake != 0)
        rigidbody_apply_impulse(rigid_body(s), (const bVector4 *)(void *)j,
                                (const bVector4 *)(void *)at);
}

int32_t smokeable_are_collisions_enabled(CollisionBody *b)
{
    return b->CollisionsDisabled == 0;
}

int32_t smokeable_get_terrain_type(CollisionBody *b)
{
    return ((Smokeable *)(void *)b)->SI->TheTerrainType;
}

float smokeable_get_mass_inverse(CollisionBody *b)
{
    Smokeable *s = (Smokeable *)(void *)b;

    if (s->AnchorStrength == 0.0f)
        return rigid_body(s)->Mass_inv;
    return 0.0f;
}

bMatrix4 *smokeable_get_inertia_tensor_inverse(CollisionBody *b)
{
    Smokeable *s = (Smokeable *)(void *)b;

    if (s->AnchorStrength == 0.0f)
        return &rigid_body(s)->I_body_inv;
    return &ZeroMatrix;
}

int32_t smokeable_is_moveable(CollisionBody *b)
{
    return ((Smokeable *)(void *)b)->AnchorStrength == 0.0f;
}

int32_t smokeable_is_blinking(CollisionBody *b)
{
    return ((Smokeable *)(void *)b)->Blinking;
}

float smokeable_get_bounciness(CollisionBody *b)
{
    return ((Smokeable *)(void *)b)->SI->Bounciness;
}

float smokeable_get_friction(CollisionBody *b)
{
    return ((Smokeable *)(void *)b)->SI->Friction;
}

int32_t smokeable_get_smoke_type(CollisionBody *b)
{
    (void)b;
    return 0;
}

void smokeable_on_lifetime_end(CollisionBody *b)
{
    (void)b;
}

static void smokeable_vt_destroy(void *self, int32_t flags)
{
    smokeable_destroy((Smokeable *)self, flags);
}

static void virginsmokeable_vt_destroy(void *self, int32_t flags)
{
    virginsmokeable_destroy((VirginSmokeable *)self, flags);
}

#define E(f) { 0, 0, (VtFn)(f) }
#define PURE { 0, 0, NULL }

// _vt$9Smokeable (0x002bcb10). Every entry's delta is 0. DoSnapshot is
// the replay's, in smokesnap.c.
static const VtEntry smokeable_vt[SMOKEABLE_VT_ENTRIES] = {
    PURE,
    E(smokeable_vt_destroy),
    E(smokeable_do_snapshot),
    E(smokeable_get_position),
    E(smokeable_get_velocity),
    E(smokeable_get_rotation),
    E(dynamiccollisionbody_set_position),
    E(dynamiccollisionbody_get_max_backup_time),
    E(smokeable_move),
    E(dynamiccollisionbody_backup),
    E(dynamiccollisionbody_interpolate),
    E(dynamiccollisionbody_recompute_auxilliaries),
    E(dynamiccollisionbody_get_current_velocities),
    E(dynamiccollisionbody_get_test_impulse_velocities),
    E(dynamiccollisionbody_set_to_physics_mode),
    E(smokeable_consider_impulse),
    E(smokeable_apply_impulse),
    E(smokeable_are_collisions_enabled),
    E(smokeable_get_terrain_type),
    E(smokeable_get_mass_inverse),
    E(smokeable_get_inertia_tensor_inverse),
    E(smokeable_is_moveable),
    E(dynamiccollisionbody_change_in_energy),
    E(smokeable_is_blinking),
    E(smokeable_get_bounciness),
    E(smokeable_get_friction),
    E(smokeable_get_smoke_type),
    E(smokeable_on_lifetime_end),
};

// _vt$9Smokeable$13PhysicsSystem (0x002bcaf0): the destructor and the
// override reached from the second base, so back by its offset.
static VtEntry smokeable_system_vt[SMOKEABLE_SYSTEM_VT_ENTRIES] = {
    PURE,
    E(smokeable_vt_destroy),
    E(smokeable_system_compute_auxiliaries),
    E(physicssystem_resolve_forces),
};

// _vt$15VirginSmokeable (0x002bcbf0).
static const VtEntry virginsmokeable_vt[COLLISIONBODY_VT_ENTRIES] = {
    PURE,
    E(virginsmokeable_vt_destroy),
    E(virginsmokeable_do_snapshot),
    E(virginsmokeable_get_position),
    E(staticcollisionbody_get_velocity),
    E(staticcollisionbody_get_rotation),
    E(staticcollisionbody_set_position),
    E(staticcollisionbody_get_max_backup_time),
    E(staticcollisionbody_move),
    E(staticcollisionbody_backup),
    E(staticcollisionbody_interpolate),
    E(staticcollisionbody_recompute_auxilliaries),
    E(staticcollisionbody_get_current_velocities),
    E(staticcollisionbody_get_test_impulse_velocities),
    E(staticcollisionbody_set_to_physics_mode),
    E(staticcollisionbody_consider_impulse),
    E(staticcollisionbody_apply_impulse),
    E(staticcollisionbody_are_collisions_enabled),
    E(virginsmokeable_get_terrain_type),
    E(staticcollisionbody_get_mass_inverse),
    E(staticcollisionbody_get_inertia_tensor_inverse),
    E(staticcollisionbody_is_moveable),
    E(staticcollisionbody_change_in_energy),
    E(collisionbody_is_blinking),
    E(staticcollisionbody_get_bounciness),
    E(staticcollisionbody_get_friction),
};

void smokeable_install_vtables(void)
{
    int16_t d = (int16_t)-(int)offsetof(Smokeable, System);

    smokeable_system_vt[0].delta = d;
    smokeable_system_vt[1].delta = d;
    smokeable_system_vt[2].delta = d;
    vt_install(SMOKEABLE_VTABLE, smokeable_vt, SMOKEABLE_VT_ENTRIES);
    vt_install(SMOKEABLE_SYSTEM_VTABLE, smokeable_system_vt,
               SMOKEABLE_SYSTEM_VT_ENTRIES);
    vt_install(VIRGINSMOKEABLE_VTABLE, virginsmokeable_vt,
               COLLISIONBODY_VT_ENTRIES);
}
