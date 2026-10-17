// Transcript harness for physcomp: the component classes' tables,
// destructors, operator new/delete, and the ten pools. Cross-checked by
// tools/physcomp_check.py, which reads the same facts out of the ELF
// without reading this file.
//
// What a table holds is printed by name -- the image's mangled name for the
// method each port entry stands for, from the registry below -- so the
// transcript says "slot 48 of _vt$5Wheel is ResolveForces__16PhysicsComponent"
// and the model says the same from the image's own table. The registry is
// the one place a port function is paired with an image name.
//
// The slots whose image code is a handful of loads and stores -- GetSize,
// both GetStates, SetState -- are run on a patterned object and printed as
// which state float went where, which the model reads off the listing. The
// arithmetic slots are run twice, once through the table and once by
// calling the port function directly, on two objects built the same way,
// and printed as same or different.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "carmodes.h"
#include "carstate.h"
#include "mellowmover.h"
#include "physcomp.h"
#include "vtable.h"

// The clock object's two globals that engine.c and drivetrain.c read.
// Defined here rather than linked from realtime.c, which would bring the
// joylog in behind it.
int32_t WorldTimer = 0;
int32_t WorldLoopCounter;   // realtime.c's too; ReplaySnapshot_Init reads it
float   WorldTimeElapsed = 0.0f;

// ------------------------------------------------------------ the names

typedef struct Named {
    const char *name;
    VtFn        fn;
} Named;

#define N(img, fn) { img, (VtFn)fn }

static const Named names[] = {
    N("_$_9RigidBody",                     vt_RigidBody_dtor),
    N("GetSize__9RigidBody",               vt_RigidBody_GetSize),
    N("GetState__9RigidBody",              vt_RigidBody_GetState),
    N("GetState__9RigidBodyPf",            vt_RigidBody_GetState_Pf),
    N("SetState__9RigidBodyPf",            vt_RigidBody_SetState_Pf),
    N("ResolveForces__9RigidBody",         vt_RigidBody_ResolveForces),
    N("GetDerivative__9RigidBodyPf",       vt_RigidBody_GetDerivative_Pf),
    N("ComputeAuxiliaries__9RigidBody",    vt_RigidBody_ComputeAuxiliaries),

    N("_$_5Wheel",                         vt_Wheel_dtor),
    N("GetSize__5Wheel",                   vt_Wheel_GetSize),
    N("GetState__5Wheel",                  vt_Wheel_GetState),
    N("GetState__5WheelPf",                vt_Wheel_GetState_Pf),
    N("SetState__5WheelPf",                vt_Wheel_SetState_Pf),
    N("GetDerivative__5WheelPf",           vt_Wheel_GetDerivative_Pf),
    N("ComputeAuxiliaries__5Wheel",        vt_Wheel_ComputeAuxiliaries),

    N("_$_10Suspension",                   vt_Suspension_dtor),
    N("GetSize__10Suspension",             vt_Suspension_GetSize),
    N("GetState__10Suspension",            vt_Suspension_GetState),
    N("GetState__10SuspensionPf",          vt_Suspension_GetState_Pf),
    N("SetState__10SuspensionPf",          vt_Suspension_SetState_Pf),
    N("GetDerivative__10SuspensionPf",     vt_Suspension_GetDerivative_Pf),
    N("ComputeAuxiliaries__10Suspension",  vt_Suspension_ComputeAuxiliaries),

    N("_$_6Engine",                        vt_Engine_dtor),
    N("GetSize__6Engine",                  vt_Engine_GetSize),
    N("GetState__6Engine",                 vt_Engine_GetState),
    N("GetState__6EnginePf",               vt_Engine_GetState_Pf),
    N("SetState__6EnginePf",               vt_Engine_SetState_Pf),
    N("GetDerivative__6EnginePf",          vt_Engine_GetDerivative_Pf),
    N("ComputeAuxiliaries__6Engine",       vt_Engine_ComputeAuxiliaries),

    N("_$_10DriveTrain",                   vt_DriveTrain_dtor),
    N("GetSize__10DriveTrain",             vt_DriveTrain_GetSize),
    N("GetState__10DriveTrain",            vt_DriveTrain_GetState),
    N("GetState__10DriveTrainPf",          vt_DriveTrain_GetState_Pf),
    N("SetState__10DriveTrainPf",          vt_DriveTrain_SetState_Pf),
    N("GetDerivative__10DriveTrainPf",     vt_DriveTrain_GetDerivative_Pf),
    N("ComputeAuxiliaries__10DriveTrain",  vt_DriveTrain_ComputeAuxiliaries),

    N("ResolveForces__16PhysicsComponent", physicscomponent_resolve_forces),

    N("_$_24TwoWheelAckermanSteering",     vt_Ackerman_dtor),
    N("SetSteering__24TwoWheelAckermanSteeringUs", vt_Ackerman_SetSteering),
    N("DoSnapshot__24TwoWheelAckermanSteeringP14ReplaySnapshot",
      vt_Ackerman_DoSnapshot),
    N("_$_8Steering",                      vt_Steering_dtor),
};

static const char *name_of(VtFn fn)
{
    size_t i;

    if (fn == NULL)
        return "NULL";
    for (i = 0; i < sizeof names / sizeof names[0]; i++)
        if (names[i].fn == fn)
            return names[i].name;
    return "unnamed";
}

static void s_tables(void)
{
    static const struct { const char *name; uint32_t addr; } t[] = {
        { "_vt$9RigidBody",                 RIGIDBODY_VTABLE },
        { "_vt$5Wheel",                     WHEEL_VTABLE },
        { "_vt$10Suspension",               SUSPENSION_VTABLE },
        { "_vt$6Engine",                    ENGINE_VTABLE },
        { "_vt$10DriveTrain",               DRIVETRAIN_VTABLE },
        { "_vt$24TwoWheelAckermanSteering", ACKERMAN_VTABLE },
        { "_vt$8Steering",                  STEERING_VTABLE },
    };
    size_t i;

    printf("== tables ==\n");
    for (i = 0; i < sizeof t / sizeof t[0]; i++) {
        int n, k;
        const VtEntry *e = vt_table(t[i].addr, &n);

        printf("%s 0x%08x entries %d\n", t[i].name, (unsigned)t[i].addr, n);
        if (e == NULL)
            continue;
        for (k = 0; k < n; k++)
            printf("  +%-2d d%d i%d %s\n", 8 * k, (int)e[k].delta,
                   (int)e[k].index, name_of(e[k].fn));
    }
}

// ------------------------------------------------------------- the pools

static const char *pool_names[10] = {
    "RigidBody", "TwoWheelAckermanSteering", "Wheel", "Engine",
    "DriveTrain", "Aerodynamics", "Suspension", "Mellovator", "MellowMover",
    "NullMover",
};

static BSlotPool **pool_ptr(int i)
{
    BSlotPool **p[10] = {
        &RigidBodySlotPool, &TwoWheelAckermanSteeringSlotPool,
        &WheelSlotPool, &EngineSlotPool, &DriveTrainSlotPool,
        &AerodynamicsSlotPool, &SuspensionSlotPool, &MellovatorSlotPool,
        &MellowMoverSlotPool, &NullMoverSlotPool,
    };
    return p[i];
}

static void print_counts(const char *tag)
{
    int i;

    printf("  %s", tag);
    for (i = 0; i < 7; i++)
        printf(" %d", bCountAllocatedSlots(*pool_ptr(i)));
    printf("\n");
}

// The records the ten pools hold. Each header asserts its sizeof is the
// image's on the 3DS, so a slot that is the record's sizeof (as
// bNewSlotPool rounds it) prints as "sizeof", which is the same line on the
// host and the handheld.
#define PORTED_POOLS 10
static const size_t pool_sizeof[PORTED_POOLS] = {
    sizeof(RigidBody), sizeof(TwoWheelAckermanSteering), sizeof(Wheel),
    sizeof(Engine), sizeof(DriveTrain), sizeof(Aerodynamics),
    sizeof(Suspension), sizeof(Mellovator), sizeof(MellowMover),
    sizeof(NullMover),
};

static void s_pools(int n)
{
    int i, nulls = 0;

    printf("== pools %d ==\n", n);
    InitPhysics(n);
    for (i = 0; i < 10; i++) {
        BSlotPool *p = *pool_ptr(i);
        char size[16];

        if (i < PORTED_POOLS
            && p->slotSize == (int)((pool_sizeof[i] + 3) & ~(size_t)3))
            snprintf(size, sizeof size, "sizeof");
        else
            snprintf(size, sizeof size, "%d", p->slotSize);
        printf("  %-24s %s slots %d size %s allocated %d flags %u\n",
               pool_names[i], bGetSlotPoolName(p), bCountTotalSlots(p), size,
               bCountAllocatedSlots(p), (unsigned)bGetSlotPoolFlags(p));
    }
    ClosePhysics();
    for (i = 0; i < 10; i++)
        nulls += *pool_ptr(i) == NULL;
    printf("  closed, %d null\n", nulls);
}

// Every class's operator new, and the slot it hands back zeroed.
static void s_new(void)
{
    struct { const char *name; void *p; size_t size; } o[7];
    int i;

    printf("== new ==\n");
    InitPhysics(2);

    // Each pool's first slot dirtied and handed back, so the new below
    // gets a slot that is not zero unless operator new clears it.
    for (i = 0; i < 7; i++) {
        BSlotPool *pool = *pool_ptr(i);
        void *s = bSlotMalloc(pool);

        memset(s, 0xAB, (size_t)pool->slotSize);
        bSlotFree(pool, s);
    }
    print_counts("before");
    o[0].name = "RigidBody";    o[0].p = rigidbody_new();    o[0].size = sizeof(RigidBody);
    o[1].name = "Wheel";        o[1].p = wheel_new();        o[1].size = sizeof(Wheel);
    o[2].name = "Suspension";   o[2].p = suspension_new();   o[2].size = sizeof(Suspension);
    o[3].name = "Engine";       o[3].p = engine_new();       o[3].size = sizeof(Engine);
    o[4].name = "DriveTrain";   o[4].p = drivetrain_new();   o[4].size = sizeof(DriveTrain);
    o[5].name = "Ackerman";     o[5].p = ackerman_new();     o[5].size = sizeof(TwoWheelAckermanSteering);
    o[6].name = "Aerodynamics"; o[6].p = aerodynamics_new(); o[6].size = sizeof(Aerodynamics);
    print_counts("after new");
    for (i = 0; i < 7; i++) {
        const unsigned char *b = o[i].p;
        size_t k, nz = 0;

        for (k = 0; k < o[i].size; k++)
            nz += b[k] != 0;
        printf("  %-12s nonzero bytes %d\n", o[i].name, (int)nz);
    }

    // The deletes, in a different order from the news, and each on its
    // own class's pool.
    aerodynamics_delete(o[6].p);
    print_counts("aero gone");
    wheel_delete(o[1].p);
    print_counts("wheel gone");
    rigidbody_delete(o[0].p);
    engine_delete(o[3].p);
    print_counts("body, engine gone");
    ackerman_delete(o[5].p);
    drivetrain_delete(o[4].p);
    suspension_delete(o[2].p);
    print_counts("all gone");

    // A slot handed back is the next one out.
    {
        void *a = wheel_new(), *b;
        wheel_delete(a);
        b = wheel_new();
        printf("  reuse %s\n", a == b ? "same slot" : "different slot");
        wheel_delete(b);
    }
    ClosePhysics();
}

// ------------------------------------------------------ the simple slots

// The state floats are 1000 + j; the array's are 2000 + i. Anything else
// is printed as its value.
static void print_moves(const char *tag, const float *dst, int ndst,
                        float base, float untouched)
{
    int i;

    for (i = 0; i < ndst; i++) {
        float v = dst[i];

        if (v == untouched)
            continue;
        if (v >= base && v < base + 64.0f && v == (float)(int)v)
            printf("  %s %d <- %d\n", tag, i, (int)(v - base));
        else
            printf("  %s %d = %.9g\n", tag, i, v);
    }
}

static void simple_slots(const char *name, void *obj, float *state,
                         int nstate)
{
    uint32_t vt = ((PhysicsComponent *)obj)->_vtable;
    const VtEntry *e;
    float arr[40];
    float *p;
    int i;

    printf("== slots %s ==\n", name);

    e = vt_slot(vt, PHYSICSCOMPONENT_VT_GET_SIZE);
    printf("  size %d\n", (int)((PhysicsGetSizeFn)e->fn)(vt_this(obj, e)));

    e = vt_slot(vt, PHYSICSCOMPONENT_VT_GET_STATE);
    p = ((PhysicsGetStateFn)e->fn)(vt_this(obj, e));
    printf("  state %s\n", p == state ? "State" : "elsewhere");

    // GetState(float *): the object's state patterned, the array not.
    for (i = 0; i < nstate; i++)
        state[i] = 1000.0f + (float)i;
    for (i = 0; i < 40; i++)
        arr[i] = -7.0f;
    e = vt_slot(vt, PHYSICSCOMPONENT_VT_GET_STATE_ARRAY);
    ((PhysicsStateArrayFn)e->fn)(vt_this(obj, e), arr);
    print_moves("get a", arr, 40, 1000.0f, -7.0f);

    // SetState(float *): the other way round.
    for (i = 0; i < nstate; i++)
        state[i] = -7.0f;
    for (i = 0; i < 40; i++)
        arr[i] = 2000.0f + (float)i;
    e = vt_slot(vt, PHYSICSCOMPONENT_VT_SET_STATE_ARRAY);
    ((PhysicsStateArrayFn)e->fn)(vt_this(obj, e), arr);
    print_moves("set s", state, nstate, 2000.0f, -7.0f);
}

static void s_simple(void)
{
    RigidBody *rb;
    Wheel *w;
    Suspension *s;
    Engine *en;
    DriveTrain *d;

    InitPhysics(1);

    // Only the vptr: none of these slots reads anything else.
    rb = rigidbody_new();
    rb->_vtable = RIGIDBODY_VTABLE;
    simple_slots("RigidBody", rb, (float *)&rb->State,
                 (int)(sizeof rb->State / sizeof(float)));

    w = wheel_new();
    w->_vtable = WHEEL_VTABLE;
    simple_slots("Wheel", w, (float *)&w->State,
                 (int)(sizeof w->State / sizeof(float)));

    s = suspension_new();
    s->_vtable = SUSPENSION_VTABLE;
    simple_slots("Suspension", s, (float *)&s->State,
                 (int)(sizeof s->State / sizeof(float)));

    en = engine_new();
    en->_vtable = ENGINE_VTABLE;
    simple_slots("Engine", en, (float *)&en->State,
                 (int)(sizeof en->State / sizeof(float)));

    d = drivetrain_new();
    d->_vtable = DRIVETRAIN_VTABLE;
    simple_slots("DriveTrain", d, (float *)&d->State,
                 (int)(sizeof d->State / sizeof(float)));

    ClosePhysics();
}

// ----------------------------------------------------- the destructors

static int  skid_calls;
static void *skid_last;

static void skid_seam(void *set)
{
    skid_calls++;
    skid_last = set;
}

static void dtor_one(const char *name, void *obj, uint32_t vt, int flags,
                     BSlotPool *pool)
{
    const VtEntry *e = vt_slot(vt, PHYSICSCOMPONENT_VT_DTOR);
    int before = pool ? bCountAllocatedSlots(pool) : -1;

    ((PhysicsDtorFn)e->fn)(vt_this(obj, e), flags);
    // A freed slot is still pool memory; only its first word -- the free
    // list's link -- is written, and the vptr is at 8.
    printf("  %-10s flags %d  vptr 0x%08x  freed %d\n", name, flags,
           (unsigned)((PhysicsComponent *)obj)->_vtable,
           pool ? before - bCountAllocatedSlots(pool) : 0);
}

static void s_dtors(void)
{
    int f;

    printf("== dtors ==\n");
    InitPhysics(1);
    physicssystem_install_vtables();
    physcomp_install_vtables();

    for (f = 0; f < 4; f++) {
        RigidBody *rb = rigidbody_new();
        Wheel *w = wheel_new();
        Suspension *s = suspension_new();
        Engine *en = engine_new();
        DriveTrain *d = drivetrain_new();
        TwoWheelAckermanSteering *a = ackerman_new();

        rb->_vtable = RIGIDBODY_VTABLE;
        w->_vtable = WHEEL_VTABLE;
        s->_vtable = SUSPENSION_VTABLE;
        en->_vtable = ENGINE_VTABLE;
        d->_vtable = DRIVETRAIN_VTABLE;
        a->base._vtable = ACKERMAN_VTABLE;

        dtor_one("RigidBody", rb, RIGIDBODY_VTABLE, f, RigidBodySlotPool);
        dtor_one("Wheel", w, WHEEL_VTABLE, f, WheelSlotPool);
        dtor_one("Suspension", s, SUSPENSION_VTABLE, f, SuspensionSlotPool);
        dtor_one("Engine", en, ENGINE_VTABLE, f, EngineSlotPool);
        dtor_one("DriveTrain", d, DRIVETRAIN_VTABLE, f, DriveTrainSlotPool);

        {
            const VtEntry *e = vt_slot(ACKERMAN_VTABLE, STEERING_VT_DTOR);
            int before = bCountAllocatedSlots(TwoWheelAckermanSteeringSlotPool);

            ((SteeringDtorFn)e->fn)(vt_this(a, e), f);
            printf("  %-10s flags %d  vptr 0x%08x  freed %d\n", "Ackerman", f,
                   (unsigned)a->base._vtable,
                   before
                   - bCountAllocatedSlots(TwoWheelAckermanSteeringSlotPool));
        }

        // Whatever the flags did not free is freed here, so each round
        // starts from empty.
        if (!(f & 1)) {
            rigidbody_delete(rb);
            wheel_delete(w);
            suspension_delete(s);
            engine_delete(en);
            drivetrain_delete(d);
            ackerman_delete(a);
        }
    }
    print_counts("left");

    // A bare Steering, from the general heap, as only a subclass would
    // make one. Flags 1 frees it with free(), which nothing can watch. It
    // starts with Ackerman's vptr -- what ~Ackerman leaves before it calls
    // ~Steering -- so the store ~Steering makes is one the line can see.
    for (f = 0; f < 2; f++) {
        Steering *st = malloc(sizeof *st);
        const VtEntry *e;

        memset(st, 0, sizeof *st);
        st->_vtable = ACKERMAN_VTABLE;
        e = vt_slot(STEERING_VTABLE, STEERING_VT_DTOR);
        ((SteeringDtorFn)e->fn)(vt_this(st, e), 2 * f);
        printf("  %-10s flags %d  vptr 0x%08x\n", "Steering", 2 * f,
               (unsigned)st->_vtable);
        free(st);
    }

    // The wheel's SkidMaker: nothing without a set, the seam with one.
    {
        static int tag;
        Wheel *w = wheel_new();

        w->_vtable = WHEEL_VTABLE;
        gSkidSetFinishedAddingFn = skid_seam;
        skid_calls = 0;
        dtor_one("Wheel", w, WHEEL_VTABLE, 2, WheelSlotPool);
        printf("  no set: seam calls %d\n", skid_calls);

        w->_vtable = WHEEL_VTABLE;
        w->TheSkidMaker.pSkidSet = &tag;
        dtor_one("Wheel", w, WHEEL_VTABLE, 3, WheelSlotPool);
        printf("  set: seam calls %d %s, pSkidSet %s\n", skid_calls,
               skid_last == &tag ? "with the set" : "with something else",
               w->TheSkidMaker.pSkidSet == &tag ? "kept" : "changed");
        gSkidSetFinishedAddingFn = NULL;
    }
    ClosePhysics();
}

// -------------------------------------------------- the arithmetic slots

static const RigidBodyInfo rbi = {
    1250.0f, 2.0f, 1.0f, 0.75f,
    { { 900.0f, 12.5f, -3.0f, 0.0f },
      { 12.5f, 2600.0f, 4.0f, 0.0f },
      { -3.0f, 4.0f, 3100.0f, 0.0f },
      { 0.0f, 0.0f, 0.0f, 1.0f } },
};

static const EngineInfo ei = {
    1000.0f, 6500.0f, 7000.0f, 0.25f,
    { 120.0f, 180.0f, 240.0f, 290.0f, 320.0f, 335.0f, 330.0f, 300.0f,
      250.0f },
    { 20.0f, 55.0f, 90.0f },
};

static void build_body(RigidBody *rb)
{
    static const bVector4 x = { 10.0f, -4.0f, 2.5f, 1.0f };
    static const bVector4 v = { 21.0f, 3.5f, -0.25f, 0.0f };
    static const bVector4 om = { 0.125f, -0.5f, 1.75f, 0.0f };
    static const bVector4 f = { 150.0f, -900.0f, 300.0f, 0.0f };
    static const bVector4 at = { 1.5f, 0.5f, -0.25f, 0.0f };
    bMatrix4 r;

    rigidbody_init(rb, &rbi);
    bIdentity(&r);
    r.v0.x = 0.6f;  r.v0.y = 0.8f;
    r.v1.x = -0.8f; r.v1.y = 0.6f;
    rigidbody_set_state(rb, &x, &r, &v, &om);
    rigidbody_compute_auxiliaries(rb);
    rigidbody_apply_force(rb, &f, &at);
}

static void build_engine(Engine *e, CarState *cs)
{
    engine_init(e, &ei, cs);
    e->State.w = 380.0f;
    e->Throttle = 0.75f;
    e->RoadTorque = -45.0f;
}

static const char *same(const void *a, const void *b, size_t n)
{
    return memcmp(a, b, n) == 0 ? "same" : "different";
}

static void s_same(void)
{
    RigidBody *r1, *r2;
    Engine *e1, *e2;
    CarState *cs;
    const VtEntry *e;
    float d1[40], d2[40];

    printf("== same ==\n");
    InitPhysics(2);
    physicssystem_install_vtables();
    physcomp_install_vtables();

    r1 = rigidbody_new();
    r2 = rigidbody_new();

    build_body(r1);
    build_body(r2);
    e = vt_slot(r1->_vtable, PHYSICSCOMPONENT_VT_RESOLVE_FORCES);
    ((PhysicsVoidFn)e->fn)(vt_this(r1, e));
    rigidbody_resolve_forces(r2);
    printf("  RigidBody +48 %s as rigidbody_resolve_forces\n",
           same(r1, r2, sizeof *r1));

    build_body(r1);
    build_body(r2);
    memset(d1, 0, sizeof d1);
    memset(d2, 0, sizeof d2);
    e = vt_slot(r1->_vtable, PHYSICSCOMPONENT_VT_GET_DERIVATIVE);
    ((PhysicsGetDerivativeFn)e->fn)(vt_this(r1, e), d1);
    rigidbody_get_derivative(r2, d2);
    printf("  RigidBody +56 %s as rigidbody_get_derivative, body %s\n",
           same(d1, d2, sizeof d1), same(r1, r2, sizeof *r1));

    build_body(r1);
    build_body(r2);
    r1->State.P.x += 500.0f;
    r2->State.P.x += 500.0f;
    e = vt_slot(r1->_vtable, PHYSICSCOMPONENT_VT_COMPUTE_AUXILIARIES);
    ((PhysicsVoidFn)e->fn)(vt_this(r1, e));
    rigidbody_compute_auxiliaries(r2);
    printf("  RigidBody +64 %s as rigidbody_compute_auxiliaries\n",
           same(r1, r2, sizeof *r1));

    cs = calloc(1, sizeof *cs);
    e1 = engine_new();
    e2 = engine_new();

    build_engine(e1, cs);
    build_engine(e2, cs);
    e = vt_slot(e1->_vtable, PHYSICSCOMPONENT_VT_RESOLVE_FORCES);
    ((PhysicsVoidFn)e->fn)(vt_this(e1, e));
    printf("  Engine +48 leaves it %s\n", same(e1, e2, sizeof *e1));

    build_engine(e1, cs);
    build_engine(e2, cs);
    memset(d1, 0, sizeof d1);
    memset(d2, 0, sizeof d2);
    e = vt_slot(e1->_vtable, PHYSICSCOMPONENT_VT_GET_DERIVATIVE);
    ((PhysicsGetDerivativeFn)e->fn)(vt_this(e1, e), d1);
    engine_get_derivative(e2, d2);
    printf("  Engine +56 %s as engine_get_derivative, engine %s\n",
           same(d1, d2, sizeof d1), same(e1, e2, sizeof *e1));

    build_engine(e1, cs);
    build_engine(e2, cs);
    e1->State.w = 9000.0f;
    e2->State.w = 9000.0f;
    e = vt_slot(e1->_vtable, PHYSICSCOMPONENT_VT_COMPUTE_AUXILIARIES);
    ((PhysicsVoidFn)e->fn)(vt_this(e1, e));
    engine_compute_auxiliaries(e2);
    printf("  Engine +64 %s as engine_compute_auxiliaries\n",
           same(e1, e2, sizeof *e1));

    // The steering's SetSteering, on two Ackermans made the same way.
    {
        CarTypeInfo *cti = calloc(1, sizeof *cti);
        TwoWheelAckermanSteering *a1 = ackerman_new();
        TwoWheelAckermanSteering *a2 = ackerman_new();

        cti->Wheels[0].PositionX = 1.35f;
        cti->Wheels[3].PositionX = -1.25f;
        cti->Wheels[0].PositionY = 0.8f;
        cti->Wheels[1].PositionY = -0.8f;
        ackerman_init(a1, cti);
        ackerman_init(a2, cti);
        e = vt_slot(a1->base._vtable, STEERING_VT_SET_STEERING);
        ((SteeringSetSteeringFn)e->fn)(vt_this(a1, e), 0x0c00);
        ackerman_set_steering(a2, 0x0c00);
        printf("  Ackerman +16 %s as ackerman_set_steering\n",
               same(a1->AckermanMatrix, a2->AckermanMatrix,
                    sizeof a1->AckermanMatrix));
        free(cti);
    }

    free(cs);
    ClosePhysics();
}

// --------------------------------------------------------- in a system

static void s_system(void)
{
    PhysicsSystem sys;
    int i;

    printf("== system ==\n");
    InitPhysics(1);
    physicssystem_install_vtables();
    physcomp_install_vtables();

    // PhysicsCar's order: the body, then a wheel and a suspension four
    // times, the engine, the drivetrain. Only the vptrs: AddComponent asks
    // nothing but the size.
    physicssystem_init(&sys);
    {
        RigidBody *rb = rigidbody_new();
        rb->_vtable = RIGIDBODY_VTABLE;
        physicssystem_add_component(&sys, (PhysicsComponent *)rb);
        printf("  + RigidBody  Size %d\n", (int)sys.Size);
    }
    for (i = 0; i < 4; i++) {
        Wheel *w = wheel_new();
        Suspension *s = suspension_new();

        w->_vtable = WHEEL_VTABLE;
        s->_vtable = SUSPENSION_VTABLE;
        physicssystem_add_component(&sys, (PhysicsComponent *)w);
        printf("  + Wheel      Size %d\n", (int)sys.Size);
        physicssystem_add_component(&sys, (PhysicsComponent *)s);
        printf("  + Suspension Size %d\n", (int)sys.Size);
    }
    {
        Engine *en = engine_new();
        DriveTrain *d = drivetrain_new();

        en->_vtable = ENGINE_VTABLE;
        d->_vtable = DRIVETRAIN_VTABLE;
        physicssystem_add_component(&sys, (PhysicsComponent *)en);
        printf("  + Engine     Size %d\n", (int)sys.Size);
        physicssystem_add_component(&sys, (PhysicsComponent *)d);
        printf("  + DriveTrain Size %d\n", (int)sys.Size);
    }
    print_counts("built");

    // The system owns them: its destructor destroys each with flags 3,
    // through the tables, and each goes back to its own pool.
    physicssystem_fini(&sys, 0);
    print_counts("after ~PhysicsSystem");
    ClosePhysics();
}

int main(void)
{
    // Unbuffered, so a transcript cut short by an abort shows where.
    setvbuf(stdout, NULL, _IONBF, 0);
    bSlotPoolManagerInit();
    rigidbody_static_init();   // the damping Tables GetDerivative reads
    vt_reset();
    physicssystem_install_vtables();
    physcomp_install_vtables();

    s_tables();
    s_pools(3);
    s_pools(1);
    s_new();
    s_simple();
    s_dtors();
    s_same();
    s_system();
    return 0;
}
