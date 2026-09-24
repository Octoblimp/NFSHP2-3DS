// physicssystem -- see physicssystem.h.

#include "physicssystem.h"

#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bticker.h"
#include "p32.h"
#include "vtable.h"

float AuxTime;

// ------------------------------------------------------------ the list

// The walk, as the listing makes it: a component's links are handles, the
// head node is the system's first eight bytes, and the loop ends when the
// next link is the system again.
static PhysicsComponent *first(PhysicsSystem *sys)
{
    return (PhysicsComponent *)p32_ptr(sys->pNext);
}

static PhysicsComponent *next(PhysicsComponent *c)
{
    return (PhysicsComponent *)p32_ptr(c->pNext);
}

static int is_head(const PhysicsSystem *sys, const PhysicsComponent *c)
{
    return (const void *)c == (const void *)sys;
}

// A node's Next and Prev, when the node may be the head. The head's links
// are the system's first two words, which is why the list works at all.
static uint32_t *link_next(void *node)
{
    return &((PhysicsComponent *)node)->pNext;
}

static uint32_t *link_prev(void *node)
{
    return &((PhysicsComponent *)node)->pPrev;
}

// ------------------------------------------------------- the dispatches

static int32_t get_size(PhysicsComponent *c)
{
    const VtEntry *e = vt_slot(c->_vtable, PHYSICSCOMPONENT_VT_GET_SIZE);

    return ((PhysicsGetSizeFn)e->fn)(vt_this(c, e));
}

static void system_compute_auxiliaries(PhysicsSystem *sys)
{
    const VtEntry *e = vt_slot(sys->_vtable,
                               PHYSICSSYSTEM_VT_COMPUTE_AUXILIARIES);

    ((PhysicsVoidFn)e->fn)(vt_this(sys, e));
}

// ~bTList<PhysicsComponent> (0x00192b78), and the loop ~PhysicsSystem
// repeats inline before calling it. `lw a3,0(s0)` after every destructor:
// the head is read again, so a component whose destructor unlinked
// something else is not followed into freed memory.
static void destroy_components(PhysicsSystem *sys)
{
    PhysicsComponent *c = first(sys);

    while (!is_head(sys, c)) {
        void *n = p32_ptr(c->pNext);
        void *p = p32_ptr(c->pPrev);
        uint32_t vt = c->_vtable;
        const VtEntry *e;

        *link_next(p) = p32_of(n);
        *link_prev(n) = p32_of(p);
        e = vt_slot(vt, PHYSICSCOMPONENT_VT_DTOR);
        ((PhysicsDtorFn)e->fn)(vt_this(c, e), 3);
        c = first(sys);
    }
}

static void tlist_fini(PhysicsSystem *sys, int32_t flags)
{
    destroy_components(sys);

    // `j ~bList`, which calls ~bNode(this, 2) -- nothing, the flag's low
    // bit being clear -- and then frees if its own flags say to. The only
    // caller passes 2.
    if (flags & 1)
        bFree(sys);
}

// ------------------------------------------------------------ the object

PhysicsSystem *physicssystem_init(PhysicsSystem *sys)
{
    sys->pNext   = p32_of(sys);
    sys->_vtable = PHYSICSSYSTEM_VTABLE;
    sys->pPrev   = p32_of(sys);
    sys->Size    = 0;
    return sys;
}

void physicssystem_fini(PhysicsSystem *sys, int32_t flags)
{
    sys->_vtable = PHYSICSSYSTEM_VTABLE;
    destroy_components(sys);
    tlist_fini(sys, 2);

    // `__builtin_delete`, which is bFree (0x0023f148) on the general heap.
    if (flags & 1)
        bFree(sys);
}

void physicssystem_add_component(PhysicsSystem *sys, PhysicsComponent *c)
{
    void *tail = p32_ptr(sys->pPrev);
    uint32_t vt = c->_vtable;
    const VtEntry *e;
    int32_t size;

    *link_next(tail) = p32_of(c);
    sys->pPrev = p32_of(c);
    c->pPrev   = p32_of(tail);
    c->pNext   = p32_of(sys);

    // Size is loaded after the call returns, not before it.
    e = vt_slot(vt, PHYSICSCOMPONENT_VT_GET_SIZE);
    size = ((PhysicsGetSizeFn)e->fn)(vt_this(c, e));
    sys->Size = sys->Size + size;
}

void physicssystem_get_derivative(PhysicsSystem *sys, float *out)
{
    PhysicsComponent *c = first(sys);
    int32_t n = 0;

    while (!is_head(sys, c)) {
        const VtEntry *e = vt_slot(c->_vtable,
                                   PHYSICSCOMPONENT_VT_GET_DERIVATIVE);

        ((PhysicsGetDerivativeFn)e->fn)(vt_this(c, e), out + n);
        n += get_size(c);
        c = next(c);
    }
}

void physicssystem_get_state(PhysicsSystem *sys, float *out)
{
    PhysicsComponent *c = first(sys);
    int32_t n = 0;

    while (!is_head(sys, c)) {
        const VtEntry *e = vt_slot(c->_vtable,
                                   PHYSICSCOMPONENT_VT_GET_STATE_ARRAY);

        ((PhysicsStateArrayFn)e->fn)(vt_this(c, e), out + n);
        n += get_size(c);
        c = next(c);
    }
}

void physicssystem_set_state(PhysicsSystem *sys, const float *in)
{
    PhysicsComponent *c = first(sys);
    int32_t n = 0;

    while (!is_head(sys, c)) {
        const VtEntry *e = vt_slot(c->_vtable,
                                   PHYSICSCOMPONENT_VT_SET_STATE_ARRAY);

        // SetState(float *) takes the array non-const in the image; it
        // only reads it.
        ((PhysicsStateArrayFn)e->fn)(vt_this(c, e), (float *)(in + n));
        n += get_size(c);
        c = next(c);
    }
}

void physicssystem_integrate_euler(PhysicsSystem *sys, float dt)
{
    float d[PHYSICSSYSTEM_MAX_STATE];
    PhysicsComponent *c;
    int32_t off = 0;

    // A component's GetSize need not be what its GetDerivative writes.
    // RigidBody answers 32 and writes 29, and the loop below advances all
    // 32 words of the state GetState hands back, so the body's three tail
    // pad words take dt times whatever the stack held at d[29..31]. On the
    // console that is a word of someone else's frame; nothing reads the
    // padding, so the only thing it can reach is a memory dump. The port
    // clears the array and the pad words stay as they were.
    memset(d, 0, sizeof d);
    physicssystem_get_derivative(sys, d);

    c = first(sys);
    while (!is_head(sys, c)) {
        int32_t size = get_size(c);
        const VtEntry *e = vt_slot(c->_vtable, PHYSICSCOMPONENT_VT_GET_STATE);
        float *st = ((PhysicsGetStateFn)e->fn)(vt_this(c, e));
        PhysicsComponent *n = next(c);   // before the state is written

        if (size > 0) {
            const float *dp = d + off;
            int32_t j;

            for (j = 0; j < size; j++)
                st[j] = st[j] + dt * dp[j];
        }
        off = off + size;
        c = n;
    }

    system_compute_auxiliaries(sys);
}

void physicssystem_integrate_runge_kutta(PhysicsSystem *sys, float dt)
{
    float d[PHYSICSSYSTEM_MAX_STATE];     // sp
    float y0[PHYSICSSYSTEM_MAX_STATE];    // sp+560
    float y[PHYSICSSYSTEM_MAX_STATE];     // sp+1120
    float k1[PHYSICSSYSTEM_MAX_STATE];    // sp+1680
    float k2[PHYSICSSYSTEM_MAX_STATE];    // sp+2240
    float k3[PHYSICSSYSTEM_MAX_STATE];    // sp+2800
    float k4[PHYSICSSYSTEM_MAX_STATE];    // sp+3360
    float third = PHYSICSSYSTEM_RK_THIRD; // f22, loaded before the first call
    float h;

    physicssystem_get_state(sys, y0);
    physicssystem_get_derivative(sys, d);
    h = dt * 0.5f;

    ArrayMultiply(k1, d, h, sys->Size);
    ArrayAdd(y, y0, k1, sys->Size);
    physicssystem_set_state(sys, y);
    system_compute_auxiliaries(sys);
    physicssystem_get_derivative(sys, d);

    ArrayMultiply(k2, d, h, sys->Size);
    ArrayAdd(y, y0, k2, sys->Size);
    physicssystem_set_state(sys, y);
    system_compute_auxiliaries(sys);
    physicssystem_get_derivative(sys, d);

    ArrayMultiply(k3, d, dt, sys->Size);
    ArrayAdd(y, y0, k3, sys->Size);
    physicssystem_set_state(sys, y);
    system_compute_auxiliaries(sys);
    physicssystem_get_derivative(sys, d);

    ArrayMultiply(k4, d, dt, sys->Size);

    ArrayMultiplyAndAdd(y, y0, k1, third, sys->Size);
    ArrayMultiplyAndAdd(y, y, k2, PHYSICSSYSTEM_RK_TWO_THIRDS, sys->Size);
    ArrayMultiplyAndAdd(y, y, k3, third, sys->Size);
    ArrayMultiplyAndAdd(y, y, k4, PHYSICSSYSTEM_RK_SIXTH, sys->Size);

    physicssystem_set_state(sys, y);
    system_compute_auxiliaries(sys);
}

void physicssystem_compute_auxiliaries(PhysicsSystem *sys)
{
    uint32_t t0 = bGetTicker();
    PhysicsComponent *c = first(sys);

    while (!is_head(sys, c)) {
        const VtEntry *e = vt_slot(c->_vtable,
                                   PHYSICSCOMPONENT_VT_COMPUTE_AUXILIARIES);

        ((PhysicsVoidFn)e->fn)(vt_this(c, e));
        c = next(c);
    }

    AuxTime = bGetTickerDifference(t0, bGetTicker());
}

void physicssystem_resolve_forces(PhysicsSystem *sys)
{
    (void)sys;
}

int32_t physicssystem_get_size(const PhysicsSystem *sys)
{
    return sys->Size;
}

// ------------------------------------------------------ the three helpers

void ArrayMultiply(float *out, const float *in, float s, int32_t n)
{
    if (n <= 0)
        return;
    do {
        *out++ = *in++ * s;
    } while (--n != 0);
}

void ArrayAdd(float *out, const float *a, const float *b, int32_t n)
{
    if (n <= 0)
        return;
    do {
        *out++ = *a++ + *b++;
    } while (--n != 0);
}

void ArrayMultiplyAndAdd(float *out, const float *a, const float *b, float s,
                         int32_t n)
{
    if (n <= 0)
        return;
    do {
        float bs = *b++ * s;
        *out++ = *a++ + bs;
    } while (--n != 0);
}

// ------------------------------------------------ PhysicsComponent's own

void physicscomponent_compute_auxiliaries(void *pc)
{
    (void)pc;
}

void physicscomponent_resolve_forces(void *pc)
{
    (void)pc;
}

// ------------------------------------------------------------ the tables

static void vt_system_dtor(void *self, int32_t flags)
{
    physicssystem_fini((PhysicsSystem *)self, flags);
}

static void vt_system_compute_auxiliaries(void *self)
{
    physicssystem_compute_auxiliaries((PhysicsSystem *)self);
}

static void vt_system_resolve_forces(void *self)
{
    physicssystem_resolve_forces((PhysicsSystem *)self);
}

// ~PhysicsComponent (0x00192438) tail-calls ~bTNode, which is ~bNode: the
// base's vptr stored, and a free only if the low flag bit is set. Every
// component class's own destructor is what the system's walk reaches, and
// those call the base with the bit clear.
static void vt_component_dtor(void *self, int32_t flags)
{
    physicscomponent_fini(self);
    if (flags & 1)
        bFree(self);
}

static const VtEntry physicssystem_vt[4] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_system_dtor },
    { 0, 0, (VtFn)vt_system_compute_auxiliaries },
    { 0, 0, (VtFn)vt_system_resolve_forces },
};

// The five NULLs are the base's __pure_virtual entries. vt_slot aborts on
// them, which is what __pure_virtual does.
static const VtEntry physicscomponent_vt[9] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_component_dtor },
    { 0, 0, NULL },
    { 0, 0, NULL },
    { 0, 0, NULL },
    { 0, 0, NULL },
    { 0, 0, (VtFn)physicscomponent_resolve_forces },
    { 0, 0, NULL },
    { 0, 0, (VtFn)physicscomponent_compute_auxiliaries },
};

void physicssystem_install_vtables(void)
{
    vt_install(PHYSICSSYSTEM_VTABLE, physicssystem_vt, 4);
    vt_install(PHYSICSCOMPONENT_VTABLE, physicscomponent_vt, 9);
}
