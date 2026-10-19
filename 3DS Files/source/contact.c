// contact -- see collisionbody.h.
//
// CollisionBody.obj's first stretch, 0x001ca170 .. 0x001cb4ec: Contact, a
// pair of bodies VClip has found inside each other, backed up to the moment
// they touched and pushed apart. Then the witness's three calls that make
// one and its collision: GetCollision and BeginCollision (0x001cbde0,
// 0x001cbe18) and TestForContact (0x001cc058; retail's 0x001d65f8, TASKS
// 73). The fourteenth and fifteenth slices of task 27. The image's inline ~Contact (0x0014c188) and
// operator delete (0x0014c330), which RemoveContacts reaches, are here too,
// and bList::AddSorted (0x00238290), which TestForContact does.
//
// The vectors are the VU's quadwords: every add, subtract and scale here is
// all four lanes, and a lane the code never writes on the stack is written
// zero, as vclip.c does. A normalise is the VU's `vrsqrt`, into Q and then
// `vaddq.x` onto vf00's zero; a length is `sqrt.s` of the sum of squares,
// summed x, then y, then z.

#include "collisionbody.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "eefpu.h"
#include "realtime.h"
#include "replay.h"
#include "vtable.h"

// ------------------------------------------------------------ the globals

BSlotPool *ContactSlotPool;

float ContactThreshold            = 0.05f;  // 0x003243d8  3d4ccccd
// Retail's WaferBias (gp-17844 of SLES_507.31, read only by FindWaferNormal
// and never written) is 0; the demo's (0x003243e0) is 0.5, which the port
// had until TASKS 73.
float WaferBias                   = 0.0f;   // 0x003243e0  3f000000
float MinimumContactImpulseFactor = 0.3f;   // 0x003243ec  3e99999a
float MinimumContactImpulseSpeed  = 0.1f;   // 0x003243f0  3dcccccd
float MaxFrictionScrapeSpeed      = 1.0f;   // 0x003243f8  3f800000

struct Collision *(*gCollisionNewFn)(CollisionBodyWitness *w, bVector3 *pt);
void (*gCollisionAddImpulseFn)(struct Collision *c, bVector3 *at,
                               bVector3 *impulse, float scrape);
void (*gCollisionDoSnapshotFn)(struct Collision *c, struct ReplaySnapshot *s);

// The literals, gp-28816 .. gp-28780. The two 0.3s and the two 4/7s are
// each loaded from a word of their own.
#define CROWBAR_STEP          0.05f         // 3d4ccccd  Crowbar's step
#define MIN_NORMAL_LENGTH     1e-6f         // 358637bd
#define CONSIDER_IMPULSE_VETO (-57575.0f)   // c760e700
#define CAR_FRICTION          0.3f          // 3e99999a  carcollisionbody's
#define SCRAPE_FRICTION       0.1f          // 3dcccccd
#define PULL_FACTOR           (-0.025f)     // bccccccd
#define PULL_LIMIT            (-0.4f)       // becccccd
#define LEVER_FACTOR          0.571428597f  // 3f124925  4/7
// `lui at,0x41f0`, and the bisection's and Crowbar's counts.
#define PULL_MIN_SPEED        30.0f
#define BISECTION_STEPS       8
#define CROWBAR_STEPS         20

// VClip's answer when the two polyhedra overlap.
#define VCLIP_PENETRATION     2

// The list head is a node standing alone; a node is the first thing in a
// Contact, so the head passes for one wherever only the links are touched.
static ContactNode *cnode(Contact *c)
{
    return (ContactNode *)(void *)c;
}

// ------------------------------------------------------------- the lanes

static void lanes_add(bVector3 *o, const bVector3 *a, const bVector3 *b)
{
    o->x = a->x + b->x;
    o->y = a->y + b->y;
    o->z = a->z + b->z;
    o->pad = a->pad + b->pad;
}

static void lanes_sub(bVector3 *o, const bVector3 *a, const bVector3 *b)
{
    o->x = a->x - b->x;
    o->y = a->y - b->y;
    o->z = a->z - b->z;
    o->pad = a->pad - b->pad;
}

static void lanes_scale(bVector3 *o, const bVector3 *v, float s)
{
    o->x = v->x * s;
    o->y = v->y * s;
    o->z = v->z * s;
    o->pad = v->pad * s;
}

// `vsub.xyzw d, vf00, v`: vf00 is (0, 0, 0, 1), so the fourth lane is
// 1 - w, not -w.
static void vf00_less(bVector3 *o, const bVector3 *v)
{
    o->x = 0.0f - v->x;
    o->y = 0.0f - v->y;
    o->z = 0.0f - v->z;
    o->pad = 1.0f - v->pad;
}

// `vmul.xyz ; vaddy.x ; vaddz.x`.
static float dot3(const bVector3 *a, const bVector3 *b)
{
    return (a->x * b->x + a->y * b->y) + a->z * b->z;
}

// `vopmula.xyz ACC, a, b ; vopmsub.xyz d, b, a` into a's register: a x b,
// and the fourth lane is a's.
static void vu_cross(bVector3 *d, const bVector3 *a, const bVector3 *b)
{
    float x = a->y * b->z - b->y * a->z;
    float y = a->z * b->x - b->z * a->x;
    float z = a->x * b->y - b->x * a->y;

    d->x = x;
    d->y = y;
    d->z = z;
    d->pad = a->pad;
}

// `vrsqrt Q,vf00w,vf01x ; vaddq.x ; vmulx.xyzw`: all four lanes over the
// length of three. The VU divides a zero length the EE's way, FLT_MAX.
static void normalize4(bVector3 *v)
{
    float inv = 0.0f + ee_div(1.0f, sqrtf(dot3(v, v)));

    lanes_scale(v, v, inv);
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
typedef bMatrix4 *(*VtMatrixFn)(void *self);
typedef float (*VtFloatFn)(void *self);
typedef int32_t (*VtBoolFn)(void *self);
typedef void (*VtVoidFn)(void *self);
typedef void (*VtTimeFn)(void *self, float t);
typedef void (*VtSetPositionFn)(void *self, bVector3 *p);
typedef void (*VtInterpolateFn)(void *self, bVector3 *pos, bMatrix4 *rot,
                                float t);
typedef void (*VtVelocitiesFn)(void *self, bVector3 *v, bVector3 *w);
typedef void (*VtOtherFn)(void *self, CollisionBody *other);
typedef float (*VtConsiderFn)(void *self, bVector3 *j, bVector3 *at);
typedef void (*VtApplyFn)(void *self, bVector3 *j, bVector3 *at);

static bVector3 *get_position(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_POSITION);

    return ((VtVectorFn)e->fn)(vt_this(b, e));
}

static bVector3 *get_velocity(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_VELOCITY);

    return ((VtVectorFn)e->fn)(vt_this(b, e));
}

static bMatrix4 *get_rotation(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_ROTATION);

    return ((VtMatrixFn)e->fn)(vt_this(b, e));
}

static void set_position(CollisionBody *b, bVector3 *p)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_SET_POSITION);

    ((VtSetPositionFn)e->fn)(vt_this(b, e), p);
}

static float get_max_backup_time(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable,
                               COLLISIONBODY_VT_GET_MAX_BACKUP_TIME);

    return ((VtFloatFn)e->fn)(vt_this(b, e));
}

static void body_move(CollisionBody *b, float t)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_MOVE);

    ((VtTimeFn)e->fn)(vt_this(b, e), t);
}

static void body_backup(CollisionBody *b, float t)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_BACKUP);

    ((VtTimeFn)e->fn)(vt_this(b, e), t);
}

static void interpolate(CollisionBody *b, bVector3 *pos, bMatrix4 *rot,
                        float t)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_INTERPOLATE);

    ((VtInterpolateFn)e->fn)(vt_this(b, e), pos, rot, t);
}

static void recompute_auxilliaries(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable,
                               COLLISIONBODY_VT_RECOMPUTE_AUXILLIARIES);

    ((VtVoidFn)e->fn)(vt_this(b, e));
}

static void get_current_velocities(CollisionBody *b, bVector3 *v,
                                   bVector3 *w)
{
    const VtEntry *e = vt_slot(b->_vtable,
                               COLLISIONBODY_VT_GET_CURRENT_VELOCITIES);

    ((VtVelocitiesFn)e->fn)(vt_this(b, e), v, w);
}

static void set_to_physics_mode(CollisionBody *b, CollisionBody *other)
{
    const VtEntry *e = vt_slot(b->_vtable,
                               COLLISIONBODY_VT_SET_TO_PHYSICS_MODE);

    ((VtOtherFn)e->fn)(vt_this(b, e), other);
}

static float consider_impulse(CollisionBody *b, bVector3 *j, bVector3 *at)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_CONSIDER_IMPULSE);

    return ((VtConsiderFn)e->fn)(vt_this(b, e), j, at);
}

static void apply_impulse(CollisionBody *b, bVector3 *j, bVector3 *at)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_APPLY_IMPULSE);

    ((VtApplyFn)e->fn)(vt_this(b, e), j, at);
}

static float get_mass_inverse(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_MASS_INVERSE);

    return ((VtFloatFn)e->fn)(vt_this(b, e));
}

static bMatrix4 *get_inertia_tensor_inverse(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable,
                               COLLISIONBODY_VT_GET_INERTIA_TENSOR_INVERSE);

    return ((VtMatrixFn)e->fn)(vt_this(b, e));
}

static int32_t is_moveable(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_IS_MOVEABLE);

    return ((VtBoolFn)e->fn)(vt_this(b, e));
}

static int32_t is_blinking(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_IS_BLINKING);

    return ((VtBoolFn)e->fn)(vt_this(b, e));
}

static int32_t are_collisions_enabled(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable,
                               COLLISIONBODY_VT_ARE_COLLISIONS_ENABLED);

    return ((VtBoolFn)e->fn)(vt_this(b, e));
}

static float get_bounciness(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_BOUNCINESS);

    return ((VtFloatFn)e->fn)(vt_this(b, e));
}

static float get_friction(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_FRICTION);

    return ((VtFloatFn)e->fn)(vt_this(b, e));
}

// ------------------------------------------------------------ the list

void init_contact(void)
{
    ContactSlotPool = bNewSlotPool((int)sizeof(Contact), 32,
                                   "ContactSlotPool", 16);
}

void close_contact(void)
{
    bDeleteSlotPool(ContactSlotPool);
    ContactSlotPool = NULL;
}

void contact_delete(void *p)
{
    bSlotFree(ContactSlotPool, p);
}

void contact_destroy(Contact *c, int32_t flags)
{
    // ~bTNode with flags 0 does nothing.
    if (flags & 1)
        contact_delete(c);
}

void contact_remove_contacts(ContactNode *list, CollisionBody *b)
{
    Contact *end = (Contact *)(void *)list;
    Contact *c, *next;

    for (c = list->next; c != end; c = next) {
        next = c->Link.next;
        if (c->pBody1 == b || c->pBody2 == b) {
            cnode(c->Link.prev)->next = next;
            cnode(next)->prev = c->Link.prev;
            contact_destroy(c, 3);
        }
    }
}

int32_t contact_time_sorting(const Contact *a, const Contact *b)
{
    return b->BackupTime < a->BackupTime ? 0 : 1;
}

// bList::AddSorted: before the first node the function answers 0 for,
// or at the tail. So the list runs from the longest backup down, and a
// tie goes after the ones already there.
static Contact *add_sorted(ContactNode *list,
                           int32_t (*fn)(const Contact *, const Contact *),
                           Contact *node)
{
    Contact *end = (Contact *)(void *)list;
    Contact *n, *prev;

    for (n = list->next; n != end; n = n->Link.next) {
        if (fn(node, n) == 0) {
            prev = n->Link.prev;
            cnode(prev)->next = node;
            n->Link.prev = node;
            node->Link.prev = prev;
            node->Link.next = n;
            return node;
        }
    }
    prev = list->prev;
    cnode(prev)->next = node;
    list->prev = node;
    node->Link.prev = prev;
    node->Link.next = end;
    return node;
}

// -------------------------------------------------------------- Contact

Contact *contact_init(Contact *c, CollisionBody *b1, CollisionBody *b2,
                      CollisionBodyWitness *w)
{
    c->pBody1 = b1;
    c->pBody2 = b2;
    c->pWitness = w;
    c->BackupTime = contact_find_contact_time(c);
    c->LoopFound = WorldLoopCounter;
    return c;
}

float contact_find_contact_time(Contact *c)
{
    bMatrix4 rot1, rot2;
    bVector3 pos1, pos2, zero;
    float lo = 0.0f, hi, t = 0.0f, a, b;
    int32_t r = 0, i;

    // rot1 is left as the stack had it; both Interpolates write it all.
    bIdentity(&rot2);
    zero.x = 0.0f;
    zero.y = 0.0f;
    zero.z = 0.0f;
    zero.pad = 0.0f;                    // never written on the PS2
    pos2 = zero;
    c->CrowbarVector = zero;
    a = get_max_backup_time(c->pBody1);
    b = get_max_backup_time(c->pBody2);
    hi = min_s(b, a);
    for (i = 0; i < BISECTION_STEPS; i++) {
        t = lo + (hi - lo) * 0.5f;
        interpolate(c->pBody1, &pos1, &rot1, t);
        interpolate(c->pBody2, &pos2, &rot2, t);
        r = vcwitness_vclip(&c->pWitness->Witness, &rot1, &pos1, &rot2,
                            &pos2);
        if (r == VCLIP_PENETRATION)
            lo = t;
        else if (c->pWitness->Witness.Distance < ContactThreshold)
            return t;
        else
            hi = t;
    }
    if (r == VCLIP_PENETRATION)
        contact_crowbar(c, t);
    return t;
}

void find_wafer_normal(bVector3 *out, TrackPolygonCollisionBody *t,
                       DynamicCollisionBody *d)
{
    const VCFace *face = t->Static.Body.pPoly->pFaces;
    bVector3 n, *p;

    n.x = face->Plane.CompressedNormal[0];
    n.y = face->Plane.CompressedNormal[1];
    n.z = face->Plane.CompressedNormal[2];
    n.pad = 0.0f;
    p = get_position(&d->Body);
    if (face->Plane.CompressedPlaneDistance - WaferBias < dot3(&n, p)) {
        *out = n;
    } else {
        out->x = 0.0f - n.x;
        out->y = 0.0f - n.y;
        out->z = 0.0f - n.z;
        out->pad = n.pad;
    }
}

void contact_crowbar(Contact *c, float t)
{
    bMatrix4 rot1, rot2;
    bVector3 pos1, pos2, n, cv, p1, p2;
    float s;
    int32_t i;

    interpolate(c->pBody1, &pos1, &rot1, t);
    interpolate(c->pBody2, &pos2, &rot2, t);
    if (c->pBody1->Type == TRACK_POLYGON_COLLISION_BODY) {
        find_wafer_normal(&n, (TrackPolygonCollisionBody *)c->pBody1,
                          (DynamicCollisionBody *)c->pBody2);
    } else if (c->pBody2->Type == TRACK_POLYGON_COLLISION_BODY) {
        find_wafer_normal(&n, (TrackPolygonCollisionBody *)c->pBody2,
                          (DynamicCollisionBody *)c->pBody1);
        vf00_less(&n, &n);
    } else {
        lanes_sub(&n, &pos2, &pos1);
        normalize4(&n);
    }
    s = 0.0f;
    for (i = 0; i < CROWBAR_STEPS; i++) {
        s = s + CROWBAR_STEP;
        lanes_scale(&cv, &n, s);
        p1 = pos1;
        p2 = pos2;
        if (is_moveable(c->pBody1))
            lanes_sub(&p1, &p1, &cv);
        if (is_moveable(c->pBody2))
            lanes_add(&p2, &p2, &cv);
        if (vcwitness_vclip(&c->pWitness->Witness, &rot1, &p1, &rot2, &p2)
            != VCLIP_PENETRATION) {
            c->CrowbarVector = cv;
            return;
        }
    }
}

void contact_resolve(Contact *c)
{
    bVector3 p1, p2;

    set_to_physics_mode(c->pBody1, c->pBody2);
    set_to_physics_mode(c->pBody2, c->pBody1);
    body_backup(c->pBody1, c->BackupTime);
    body_backup(c->pBody2, c->BackupTime);
    p1 = *get_position(c->pBody1);
    p2 = *get_position(c->pBody2);
    if (is_moveable(c->pBody1))
        lanes_sub(&p1, &p1, &c->CrowbarVector);
    if (is_moveable(c->pBody2))
        lanes_add(&p2, &p2, &c->CrowbarVector);
    set_position(c->pBody1, &p1);
    set_position(c->pBody2, &p2);
    recompute_auxilliaries(c->pBody1);
    recompute_auxilliaries(c->pBody2);
    contact_collision_impulse(c);
    recompute_auxilliaries(c->pBody1);
    recompute_auxilliaries(c->pBody2);
    body_move(c->pBody1, c->BackupTime);
    body_move(c->pBody2, c->BackupTime);
}

void contact_find_contact_point_and_normal(Contact *c, bVector3 *point,
                                           bVector3 *normal)
{
    bVector3 a, b, *q1, *q2;
    float len;

    bMulMatrixVec3(&a, get_rotation(c->pBody1), &c->pWitness->Witness.CP1);
    bMulMatrixVec3(&b, get_rotation(c->pBody2), &c->pWitness->Witness.CP2);
    lanes_add(&a, &a, get_position(c->pBody1));
    lanes_add(&b, &b, get_position(c->pBody2));
    lanes_add(point, &a, &b);
    lanes_scale(point, point, 0.5f);
    if (c->pBody1->Dynamic == 0) {
        find_wafer_normal(normal, (TrackPolygonCollisionBody *)c->pBody1,
                          (DynamicCollisionBody *)c->pBody2);
    } else if (c->pBody2->Dynamic == 0) {
        find_wafer_normal(normal, (TrackPolygonCollisionBody *)c->pBody2,
                          (DynamicCollisionBody *)c->pBody1);
        vf00_less(normal, normal);
    } else {
        lanes_sub(normal, &b, &a);
        len = sqrtf(dot3(normal, normal));
        if (len < MIN_NORMAL_LENGTH) {
            // The two closest points coincide: between the centres.
            q2 = get_position(c->pBody2);
            q1 = get_position(c->pBody1);
            lanes_sub(normal, q2, q1);
            normalize4(normal);
        } else {
            lanes_scale(normal, normal, 1.0f / len);
        }
    }
}

void contact_find_planar_collision_contact_point(Contact *c, bVector3 *point)
{
    bVector3 d, up, e, r, *q1, *q2;

    q2 = get_position(c->pBody2);
    q1 = get_position(c->pBody1);
    lanes_sub(&d, q2, q1);
    normalize4(&d);
    up.x = 0.0f;
    up.y = 0.0f;
    up.z = 1.0f;
    up.pad = 0.0f;                      // never written on the PS2
    lanes_scale(&e, &d, -dot3(&d, &up));
    lanes_add(&e, &e, &up);
    normalize4(&e);
    q1 = get_position(c->pBody1);
    lanes_sub(&r, point, q1);
    lanes_scale(&e, &e, -dot3(&r, &e));
    lanes_add(point, &e, point);
}

void get_contact_point_velocity(bVector3 *out, bVector3 *v, bVector3 *w,
                                bVector3 *r)
{
    bVector3 x;

    vu_cross(&x, w, r);
    lanes_add(out, v, &x);
}

float denominator_term(bMatrix4 *m, bVector3 *a, bVector3 *n)
{
    bVector3 t, u, s;

    vu_cross(&t, a, n);
    bMulMatrixVec3(&u, m, &t);
    vu_cross(&s, &u, a);
    return dot3(n, &s);
}

static void add_impulse(struct Collision *coll, bVector3 *at,
                        bVector3 *impulse, float scrape)
{
    if (gCollisionAddImpulseFn == NULL) {
        fprintf(stderr, "contact_collision_impulse: Collision is not "
                        "ported\n");
        abort();
    }
    gCollisionAddImpulseFn(coll, at, impulse, scrape);
}

void contact_collision_impulse(Contact *c)
{
    bVector3 point, normal, r1, r2, v1, w1, v2, w2, vp1, vp2, vrel, vt;
    bVector3 jv, vel, f, jt, jn;
    struct Collision *coll;
    CollisionBody *scraper;
    float vn, e, m1, m2, num, denom, mmax, k, j, jmin, cn1, cn2, least;
    float mu, fr1, fr2, vtl, speed, pull, len;
    int32_t negative;

    contact_find_contact_point_and_normal(c, &point, &normal);
    coll = cbwitness_get_collision(c->pWitness, &point);
    lanes_sub(&r1, &point, get_position(c->pBody1));
    lanes_sub(&r2, &point, get_position(c->pBody2));
    for (;;) {
        get_current_velocities(c->pBody1, &v1, &w1);
        get_current_velocities(c->pBody2, &v2, &w2);
        get_contact_point_velocity(&vp1, &v1, &w1, &r1);
        get_contact_point_velocity(&vp2, &v2, &w2, &r2);
        lanes_sub(&vrel, &vp2, &vp1);
        vn = dot3(&vrel, &normal);
        lanes_scale(&vt, &normal, -vn);
        lanes_add(&vt, &vt, &vrel);
        if (0.0f <= vn)
            return;

        // The impulse along the normal: the bouncier body's restitution,
        // and never less than a floor that grows with the closing speed
        // up to 0.1 and is shared by the lighter side.
        e = get_bounciness(c->pBody1);
        e = max_s(get_bounciness(c->pBody2), e);
        m1 = get_mass_inverse(c->pBody1);
        m2 = get_mass_inverse(c->pBody2);
        num = -(e + 1.0f) * vn;
        denom = m1 + m2;
        denom = denom + denominator_term(
            get_inertia_tensor_inverse(c->pBody1), &r1, &normal);
        denom = denom + denominator_term(
            get_inertia_tensor_inverse(c->pBody2), &r2, &normal);
        mmax = max_s(m2, m1);
        k = fabsf(vn) / MinimumContactImpulseSpeed;
        if (1.0f < k)
            k = 1.0f;
        j = num / denom;
        jmin = k * MinimumContactImpulseFactor / mmax;
        if (j < jmin)
            j = jmin;

        // Each body is asked how much of it it will take, the second
        // first; the first is asked about the impulse as the second left
        // it, turned round. A negative answer is the last round.
        lanes_scale(&jv, &normal, j);
        cn2 = consider_impulse(c->pBody2, &jv, &r2);
        vf00_less(&jv, &jv);
        cn1 = consider_impulse(c->pBody1, &jv, &r1);
        if (cn1 == CONSIDER_IMPULSE_VETO)
            return;
        if (cn2 == CONSIDER_IMPULSE_VETO)
            return;
        negative = 1;
        if (cn1 < 0.0f)
            cn1 = -cn1;
        else if (cn2 < 0.0f)
            cn2 = -cn2;
        else
            negative = 0;
        least = min_s(cn2, cn1);
        j = least * j;

        // Friction against the slide: the rougher body's, but a car (whose
        // friction is 0.3) against something that cannot move scrapes at
        // 0.1, and slower than MaxFrictionScrapeSpeed it fades.
        fr1 = get_friction(c->pBody1);
        fr2 = get_friction(c->pBody2);
        mu = max_s(fr2, fr1);
        scraper = NULL;
        if (m1 == 0.0f && fr2 == CAR_FRICTION) {
            scraper = c->pBody2;
            mu = SCRAPE_FRICTION;
        } else if (m2 == 0.0f && fr1 == CAR_FRICTION) {
            scraper = c->pBody1;
            mu = SCRAPE_FRICTION;
        }
        vtl = sqrtf(dot3(&vt, &vt));
        k = j * mu;
        if (vtl < MaxFrictionScrapeSpeed)
            k = k * (vtl / MaxFrictionScrapeSpeed);
        // A contact with no slide at all -- a car dropped straight onto
        // flat ground -- divides by zero here, and gets FLT_MAX.
        lanes_scale(&f, &vt, ee_div(-k, vtl));
        lanes_scale(&jv, &normal, j);
        lanes_add(&jt, &jv, &f);
        vf00_less(&jn, &jt);

        // A scraping car past 30 is pulled back by a fortieth of its
        // velocity, never more than 0.4 of it and flat on the ground, and
        // its lever arm is shortened to match.
        if (scraper != NULL) {
            vel = *get_velocity(scraper);
            speed = sqrtf(dot3(&vel, &vel));
            if (PULL_MIN_SPEED < speed) {
                pull = PULL_FACTOR;
                if (speed * PULL_FACTOR < PULL_LIMIT)
                    pull = PULL_LIMIT / speed;
                lanes_scale(&vel, &vel, pull);
                vel.z = 0.0f;
                // The image compares m1 with the lane it has just zeroed.
                if (m1 == vel.z) {
                    len = sqrtf(dot3(&jt, &jt));
                    lanes_add(&jt, &jt, &vel);
                    if (1.0f < speed + len)
                        lanes_scale(&r2, &r2,
                                    len / (speed * LEVER_FACTOR + len));
                } else {
                    len = sqrtf(dot3(&jn, &jn));
                    lanes_add(&jn, &jn, &vel);
                    if (1.0f < speed + len)
                        lanes_scale(&r1, &r1,
                                    len / (speed * LEVER_FACTOR + len));
                }
            }
        }

        apply_impulse(c->pBody2, &jt, &r2);
        apply_impulse(c->pBody1, &jn, &r1);
        add_impulse(coll, &point, &jt, vtl);
        if (least == 1.0f)
            return;
        if (negative)
            return;
    }
}

// --------------------------------------------------- CollisionBodyWitness

struct Collision *cbwitness_get_collision(CollisionBodyWitness *w,
                                          bVector3 *pt)
{
    if (w->pCollision == NULL)
        cbwitness_begin_collision(w, pt);
    return w->pCollision;
}

void cbwitness_begin_collision(CollisionBodyWitness *w, bVector3 *pt)
{
    int32_t n;

    // `lbu`, `addiu`, `sb`: a byte that wraps.
    w->pBody1->NumCollisions = (int8_t)(w->pBody1->NumCollisions + 1);
    w->pBody2->NumCollisions = (int8_t)(w->pBody2->NumCollisions + 1);
    n = TheCollisionStats.NumCollisions + 1;
    if (TheCollisionStats.HighestNumCollisions < n)
        TheCollisionStats.HighestNumCollisions = n;
    TheCollisionStats.NumCollisions = n;
    if (gCollisionNewFn == NULL) {
        fprintf(stderr, "cbwitness_begin_collision: Collision is not "
                        "ported\n");
        abort();
    }
    w->pCollision = gCollisionNewFn(w, pt);
}

// 0x001d6168. A restore that finds a Collision begins one at no point, so
// the constructor zeroes InitialContactPoint, and the Collision's own
// snapshot fills it in.
void cbwitness_do_snapshot(CollisionBodyWitness *w, ReplaySnapshot *s)
{
    int8_t has;

    ReplaySnapshot_BeginSection(s, w, "CollisionBodyWitness");
    vcwitness_do_snapshot(&w->Witness, s);
    has = w->pCollision != NULL;
    ReplaySnapshot_MoveChar(s, &has, 1);
    if (has) {
        if (s->RestoringSnapshotFlag)
            cbwitness_begin_collision(w, NULL);
        if (gCollisionDoSnapshotFn == NULL) {
            fprintf(stderr, "cbwitness_do_snapshot: Collision is not "
                            "ported\n");
            abort();
        }
        gCollisionDoSnapshotFn(w->pCollision, s);
    }
    ReplaySnapshot_EndSection(s);
}

static Contact *contact_new(void)
{
    Contact *c = bSlotOMalloc(ContactSlotPool);

    if (c == NULL) {
        fprintf(stderr, "contact_new: ContactSlotPool is full\n");
        abort();
    }
    return c;
}

// Retail's 0x001d65f8, the demo's 0x001cc058 with two things added: it
// asks both bodies whether their collisions are on before VClip, and each
// car it hands on in a contact gets LastCollisionTime stamped, beside the
// yaw stamp the demo's gave.
void cbwitness_test_for_contact(CollisionBodyWitness *w, ContactNode *list)
{
    bMatrix4 *r1, *r2;
    bVector3 *p1, *p2;
    int32_t r;

    if (!are_collisions_enabled(w->pBody1))
        return;
    if (!are_collisions_enabled(w->pBody2))
        return;
    r1 = get_rotation(w->pBody1);
    p1 = get_position(w->pBody1);
    r2 = get_rotation(w->pBody2);
    p2 = get_position(w->pBody2);
    r = vcwitness_vclip(&w->Witness, r1, p1, r2, p2);
    if (PrintThisTime)
        PrintThisTime = 0;
    if (r != VCLIP_PENETRATION)
        return;

    // A blinking car goes through another car: only the stamp.
    if (is_blinking(w->pBody1) || is_blinking(w->pBody2)) {
        if (w->pBody1->Dynamic != 0 && w->pBody2->Dynamic != 0) {
            if (w->pBody1->Type == CAR_COLLISION_BODY)
                ((CarCollisionBody *)w->pBody1)->LastPenetrationTime
                    .PackedTime = (uint32_t)WorldTimer;
            if (w->pBody2->Type == CAR_COLLISION_BODY)
                ((CarCollisionBody *)w->pBody2)->LastPenetrationTime
                    .PackedTime = (uint32_t)WorldTimer;
            return;
        }
    }
    if (w->pBody1->Type == CAR_COLLISION_BODY) {
        CarCollisionBody *c = (CarCollisionBody *)w->pBody1;

        if (is_yaw_control_inducing_collision_body(w->pBody2))
            c->LastYawControlCollisionTime.PackedTime = (uint32_t)WorldTimer;
        c->LastCollisionTime.PackedTime = (uint32_t)WorldTimer;
    }
    if (w->pBody2->Type == CAR_COLLISION_BODY) {
        CarCollisionBody *c = (CarCollisionBody *)w->pBody2;

        if (is_yaw_control_inducing_collision_body(w->pBody1))
            c->LastYawControlCollisionTime.PackedTime = (uint32_t)WorldTimer;
        c->LastCollisionTime.PackedTime = (uint32_t)WorldTimer;
    }
    add_sorted(list, contact_time_sorting,
               contact_init(contact_new(), w->pBody1, w->pBody2, w));
}
