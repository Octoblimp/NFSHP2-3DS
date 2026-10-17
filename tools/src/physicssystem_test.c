// Transcript harness for PhysicsSystem, the ticker and p32. Cross-checked
// by tools/physicssystem_check.py, which models the same behaviour from the
// disassembly without reading this file.
//
// The components are fakes: a record with the PhysicsComponent header and
// a handful of fields, and two tables installed at addresses the image does
// not use. Every slot logs what it was asked and where, so the transcript
// is the order of the system's calls as much as it is their results. Some
// fakes misbehave on purpose -- splice a new component in after themselves,
// shrink, move the system's Size -- because each of those is how one
// detail of the listing's walk becomes visible.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bticker.h"
#include "p32.h"
#include "physicssystem.h"
#include "vtable.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

static unsigned fbits(float f)
{
    unsigned u;
    memcpy(&u, &f, 4);
    return u;
}

// ------------------------------------------------------------- arrays
//
// A pointer the system hands a component is printed as the array it points
// into and the offset: `a<k>+<n>`, where k counts arrays in the order the
// current operation first touched them. The port's arrays are 140 floats
// each, so a pointer into one is never within 140 of another's start.

#define ARR PHYSICSSYSTEM_MAX_STATE

static uintptr_t bases[16];
static int nbases;

static void arr_reset(void)
{
    nbases = 0;
}

static void arr_name(const float *p, char *buf)
{
    uintptr_t a = (uintptr_t)p;
    int i;

    for (i = 0; i < nbases; i++) {
        if (a >= bases[i] && a < bases[i] + ARR * sizeof(float)) {
            sprintf(buf, "a%d+%d", i, (int)((a - bases[i]) / sizeof(float)));
            return;
        }
    }
    if (nbases == 16) {
        printf("too many arrays\n");
        exit(2);
    }
    bases[nbases] = a;
    sprintf(buf, "a%d+0", nbases);
    nbases++;
}

// ------------------------------------------------------------- the ticks

static uint32_t tk_next, tk_step, tk_accel;

static uint32_t tk_source(void)
{
    uint32_t v = tk_next;
    tk_next += tk_step;
    tk_step += tk_accel;
    return v;
}

static void ticks(uint32_t start, uint32_t step, uint32_t accel)
{
    tk_next = start;
    tk_step = step;
    tk_accel = accel;
    bSetTickerSource(tk_source);
}

// ------------------------------------------------------------- the fakes

#define FAKE_VT_A   0x00a00000u
#define FAKE_VT_B   0x00a00100u
#define FAKE_SYS_VT 0x00b00000u

enum {
    FK_INSERT_DERIV    = 1,    // GetDerivative splices `pending` in after it
    FK_INSERT_GETSTATE = 2,    // GetState() does
    FK_INSERT_AUX      = 4,    // ComputeAuxiliaries does
    FK_MEDDLE          = 8,    // GetSize adds 100 to the system's Size
    FK_SHRINK          = 16,   // GetDerivative drops its own size by one
    FK_UNLINK_NEXT     = 32,   // the destructor unlinks its old next node
    FK_DROP            = 64,   // SetState drops the system's Size by one
};

typedef struct Fake {
    uint32_t pNext, pPrev, _vtable;
    int32_t  id, size, flags, heap;
    float    state[8];
    float    gain, bias, aux;
    struct Fake *pending;
} Fake;

// A component that is not at the front of its object: table B adjusts by
// -offsetof(Outer, f), and its methods check the tag they land on.
#define OUTER_TAG 0xfeed0badu

typedef struct Outer {
    uint32_t tag[4];
    Fake     f;
} Outer;

// And a system that is not at the front of its object, the way
// PhysicsVehicle sits eight bytes into PhysicsCar.
#define SYSOUTER_TAG 0x5eed0badu

typedef struct SysOuter {
    uint32_t      tag[2];
    PhysicsSystem sys;
} SysOuter;

static PhysicsSystem *g_sys;

static const char *node_name(uint32_t h)
{
    static char buf[4][16];
    static int k;
    void *p = p32_ptr(h);
    char *b = buf[k++ & 3];

    if (p == (void *)g_sys)
        return "head";
    sprintf(b, "c%d", (int)((Fake *)p)->id);
    return b;
}

static void splice_after(Fake *f)
{
    Fake *z = f->pending;
    PhysicsComponent *n = (PhysicsComponent *)p32_ptr(f->pNext);

    f->pending = NULL;
    z->pNext = f->pNext;
    z->pPrev = p32_of(f);
    n->pPrev = p32_of(z);
    f->pNext = p32_of(z);
    printf("  insert c%d after c%d\n", (int)z->id, (int)f->id);
}

static int32_t fk_get_size(Fake *f, const char *via)
{
    printf("  %ssize c%d -> %d\n", via, (int)f->id, (int)f->size);
    if (f->flags & FK_MEDDLE) {
        g_sys->Size += 100;
        printf("  meddle Size -> %d\n", (int)g_sys->Size);
    }
    return f->size;
}

static float *fk_get_state(Fake *f, const char *via)
{
    printf("  %sstate c%d\n", via, (int)f->id);
    if ((f->flags & FK_INSERT_GETSTATE) && f->pending)
        splice_after(f);
    return f->state;
}

static void fk_get_state_array(Fake *f, float *out, const char *via)
{
    char nm[32];
    int i;

    arr_name(out, nm);
    printf("  %sgetstate c%d %s", via, (int)f->id, nm);
    for (i = 0; i < f->size; i++) {
        out[i] = f->state[i];
        printf(" %.9g", out[i]);
    }
    printf("\n");
}

static void fk_set_state_array(Fake *f, float *in, const char *via)
{
    char nm[32];
    int i;

    arr_name(in, nm);
    printf("  %ssetstate c%d %s", via, (int)f->id, nm);
    for (i = 0; i < f->size; i++) {
        f->state[i] = in[i];
        printf(" %.9g", in[i]);
    }
    printf("\n");
    if (f->flags & FK_DROP) {
        g_sys->Size -= 1;
        printf("  drop Size -> %d\n", (int)g_sys->Size);
    }
}

static float *fk_get_derivative(Fake *f, float *out, const char *via)
{
    char nm[32];
    int i;

    arr_name(out, nm);
    printf("  %sderiv c%d %s", via, (int)f->id, nm);
    for (i = 0; i < f->size; i++) {
        float a = f->gain * f->state[i];
        float b = f->bias * (float)(i + 1);
        float c = 0.25f * f->aux;
        out[i] = (a + b) + c;
        printf(" %.9g", out[i]);
    }
    printf("\n");
    if ((f->flags & FK_SHRINK) && f->size > 0) {
        f->size -= 1;
        printf("  shrink c%d -> %d\n", (int)f->id, (int)f->size);
    }
    if ((f->flags & FK_INSERT_DERIV) && f->pending)
        splice_after(f);
    return out;
}

static void fk_resolve(Fake *f, const char *via)
{
    printf("  %sresolve c%d\n", via, (int)f->id);
}

static void fk_aux(Fake *f, const char *via)
{
    float s = 0.0f;
    int i;

    for (i = 0; i < f->size; i++)
        s = s + f->state[i];
    f->aux = f->aux * 0.5f + s;
    printf("  %saux c%d %.9g\n", via, (int)f->id, f->aux);
    if ((f->flags & FK_INSERT_AUX) && f->pending)
        splice_after(f);
}

// The links a destroyed component still holds are printed before anything
// else happens to them: the system's unlink rewrites its neighbours, never
// the component. So is the system's vptr, which ~PhysicsSystem stores
// before the walk rather than after it.
static void fk_dtor(Fake *f, int32_t flags, const char *via)
{
    printf("  %sdtor c%d %d links %s %s sysvt %08x\n", via, (int)f->id,
           (int)flags, node_name(f->pNext), node_name(f->pPrev),
           (unsigned)g_sys->_vtable);
    if (f->flags & FK_UNLINK_NEXT) {
        PhysicsComponent *n = (PhysicsComponent *)p32_ptr(f->pNext);

        if ((void *)n != (void *)g_sys) {
            PhysicsComponent *np = (PhysicsComponent *)p32_ptr(n->pPrev);
            PhysicsComponent *nn = (PhysicsComponent *)p32_ptr(n->pNext);

            np->pNext = n->pNext;
            nn->pPrev = n->pPrev;
            printf("  unlink c%d\n", (int)((Fake *)n)->id);
        }
    }
}

// Table A: the component is the object.
static void a_dtor(void *s, int32_t fl)
{
    Fake *f = (Fake *)s;
    fk_dtor(f, fl, "");
    if ((fl & 1) && f->heap)
        free(f);
}
static int32_t a_size(void *s)            { return fk_get_size((Fake *)s, ""); }
static float  *a_state(void *s)           { return fk_get_state((Fake *)s, ""); }
static void    a_gsa(void *s, float *o)   { fk_get_state_array((Fake *)s, o, ""); }
static void    a_ssa(void *s, float *i)   { fk_set_state_array((Fake *)s, i, ""); }
static void    a_res(void *s)             { fk_resolve((Fake *)s, ""); }
static float  *a_der(void *s, float *o)   { return fk_get_derivative((Fake *)s, o, ""); }
static void    a_aux(void *s)             { fk_aux((Fake *)s, ""); }

// Table B: the component is 16 bytes into an Outer.
static Outer *outer(void *s)
{
    Outer *o = (Outer *)s;
    if (o->tag[0] != OUTER_TAG) {
        printf("bad this for table B\n");
        exit(3);
    }
    return o;
}
static void b_dtor(void *s, int32_t fl)
{
    Outer *o = outer(s);
    fk_dtor(&o->f, fl, "B:");
    if ((fl & 1) && o->f.heap)
        free(o);
}
static int32_t b_size(void *s)            { return fk_get_size(&outer(s)->f, "B:"); }
static float  *b_state(void *s)           { return fk_get_state(&outer(s)->f, "B:"); }
static void    b_gsa(void *s, float *o)   { fk_get_state_array(&outer(s)->f, o, "B:"); }
static void    b_ssa(void *s, float *i)   { fk_set_state_array(&outer(s)->f, i, "B:"); }
static void    b_res(void *s)             { fk_resolve(&outer(s)->f, "B:"); }
static float  *b_der(void *s, float *o)   { return fk_get_derivative(&outer(s)->f, o, "B:"); }
static void    b_aux(void *s)             { fk_aux(&outer(s)->f, "B:"); }

// The derived system's table: the system is 8 bytes into a SysOuter.
static SysOuter *sysouter(void *s)
{
    SysOuter *o = (SysOuter *)s;
    if (o->tag[0] != SYSOUTER_TAG) {
        printf("bad this for the derived system\n");
        exit(4);
    }
    return o;
}
static void d_dtor(void *s, int32_t fl)
{
    printf("  derived-dtor %d\n", (int)fl);
    physicssystem_fini(&sysouter(s)->sys, fl & ~1);
}
static void d_aux(void *s)
{
    printf("  derived-aux\n");
    physicssystem_compute_auxiliaries(&sysouter(s)->sys);
}
static void d_res(void *s)
{
    (void)sysouter(s);
    printf("  derived-resolve\n");
}

static VtEntry vt_a[9], vt_b[9], vt_d[4];

static void install(void)
{
    int16_t db = (int16_t)-(int16_t)offsetof(Outer, f);
    int16_t dd = (int16_t)-(int16_t)offsetof(SysOuter, sys);
    VtFn fa[9] = { NULL, (VtFn)a_dtor, (VtFn)a_size, (VtFn)a_state,
                   (VtFn)a_gsa, (VtFn)a_ssa, (VtFn)a_res, (VtFn)a_der,
                   (VtFn)a_aux };
    VtFn fb[9] = { NULL, (VtFn)b_dtor, (VtFn)b_size, (VtFn)b_state,
                   (VtFn)b_gsa, (VtFn)b_ssa, (VtFn)b_res, (VtFn)b_der,
                   (VtFn)b_aux };
    VtFn fd[4] = { NULL, (VtFn)d_dtor, (VtFn)d_aux, (VtFn)d_res };
    int i;

    for (i = 0; i < 9; i++) {
        vt_a[i].delta = 0;
        vt_a[i].index = 0;
        vt_a[i].fn = fa[i];
        vt_b[i].delta = db;
        vt_b[i].index = 0;
        vt_b[i].fn = fb[i];
    }
    for (i = 0; i < 4; i++) {
        vt_d[i].delta = dd;
        vt_d[i].index = 0;
        vt_d[i].fn = fd[i];
    }

    vt_reset();
    p32_reset();
    physicssystem_install_vtables();
    vt_install(FAKE_VT_A, vt_a, 9);
    vt_install(FAKE_VT_B, vt_b, 9);
    vt_install(FAKE_SYS_VT, vt_d, 4);
    arr_reset();
    bSetTickerSource(NULL);
}

static void fake_init(Fake *f, int id, int size, int flags, float gain,
                      float bias, float st0)
{
    int i;

    memset(f, 0, sizeof *f);
    f->_vtable = FAKE_VT_A;
    f->id = id;
    f->size = size;
    f->flags = flags;
    f->gain = gain;
    f->bias = bias;
    for (i = 0; i < 8; i++)
        f->state[i] = st0 + (float)i * 0.25f;
}

static void outer_init(Outer *o, int id, int size, int flags, float gain,
                       float bias, float st0)
{
    memset(o, 0, sizeof *o);
    o->tag[0] = OUTER_TAG;
    fake_init(&o->f, id, size, flags, gain, bias, st0);
    o->f._vtable = FAKE_VT_B;
}

static Fake *heap_fake(int id, int size, int flags)
{
    Fake *f = (Fake *)malloc(sizeof *f);
    fake_init(f, id, size, flags, 1.0f, 0.0f, (float)id);
    f->heap = 1;
    return f;
}

static void ring(const char *tag, PhysicsSystem *s)
{
    PhysicsComponent *c;
    int n;

    printf("%s size %d fwd", tag, (int)s->Size);
    c = (PhysicsComponent *)p32_ptr(s->pNext);
    for (n = 0; (void *)c != (void *)s && n < 20; n++) {
        printf(" c%d", (int)((Fake *)c)->id);
        c = (PhysicsComponent *)p32_ptr(c->pNext);
    }
    printf(" | back");
    c = (PhysicsComponent *)p32_ptr(s->pPrev);
    for (n = 0; (void *)c != (void *)s && n < 20; n++) {
        printf(" c%d", (int)((Fake *)c)->id);
        c = (PhysicsComponent *)p32_ptr(c->pPrev);
    }
    printf("\n");
}

static void dump_fake(const Fake *f)
{
    int i;

    printf("c%d size %d aux %.9g st", (int)f->id, (int)f->size, f->aux);
    for (i = 0; i < 8; i++)
        printf(" %.9g", f->state[i]);
    printf("\n");
}

static void dump_buf(const char *tag, const float *b)
{
    int i;

    printf("%s", tag);
    for (i = 0; i < 8; i++)
        printf(" %.9g", b[i]);
    printf("\n");
}

static void fill(float *b, float v)
{
    int i;
    for (i = 0; i < ARR; i++)
        b[i] = v;
}

static void add(PhysicsSystem *s, Fake *f)
{
    physicssystem_add_component(s, (PhysicsComponent *)f);
}

// ------------------------------------------------------------ scenarios

static void s_layout(void)
{
    printf("[layout]\n");
    printf("layout %d %d %d %d %d\n", (int)sizeof(PhysicsSystem),
           (int)offsetof(PhysicsSystem, Size),
           (int)offsetof(PhysicsSystem, _vtable),
           (int)sizeof(PhysicsComponent),
           (int)offsetof(PhysicsComponent, _vtable));
    printf("vt %08x %08x\n", PHYSICSSYSTEM_VTABLE, PHYSICSCOMPONENT_VTABLE);
    printf("rk %08x %08x %08x\n", fbits(PHYSICSSYSTEM_RK_THIRD),
           fbits(PHYSICSSYSTEM_RK_TWO_THIRDS), fbits(PHYSICSSYSTEM_RK_SIXTH));
    printf("slots %d %d %d %d %d %d %d %d | %d %d %d\n",
           PHYSICSCOMPONENT_VT_DTOR, PHYSICSCOMPONENT_VT_GET_SIZE,
           PHYSICSCOMPONENT_VT_GET_STATE, PHYSICSCOMPONENT_VT_GET_STATE_ARRAY,
           PHYSICSCOMPONENT_VT_SET_STATE_ARRAY,
           PHYSICSCOMPONENT_VT_RESOLVE_FORCES,
           PHYSICSCOMPONENT_VT_GET_DERIVATIVE,
           PHYSICSCOMPONENT_VT_COMPUTE_AUXILIARIES,
           PHYSICSSYSTEM_VT_DTOR, PHYSICSSYSTEM_VT_COMPUTE_AUXILIARIES,
           PHYSICSSYSTEM_VT_RESOLVE_FORCES);
    printf("max %d\n", PHYSICSSYSTEM_MAX_STATE);
    printf("tick %08x\n", fbits(BTICKER_ASSUMED_HZ));
}

static void s_add(void)
{
    PhysicsSystem sys;
    Fake c1, c2, c4;
    Outer o3;
    int i;

    printf("[add]\n");
    install();
    memset(&sys, 0xab, sizeof sys);
    g_sys = &sys;
    // Two statements: C leaves the order of a call's arguments open, and
    // one build read the vptr before the init had written it.
    i = physicssystem_init(&sys) == &sys;
    printf("init %d %08x\n", i, (unsigned)sys._vtable);
    ring("empty", &sys);

    fake_init(&c1, 1, 3, 0, 0.5f, 0.125f, 1.0f);
    fake_init(&c2, 2, 0, 0, 1.0f, 1.0f, 0.0f);
    outer_init(&o3, 3, 2, 0, -1.5f, 2.0f, -3.0f);
    fake_init(&c4, 4, 1, FK_MEDDLE, 3.0f, -0.5f, 7.0f);

    printf("add c1\n");
    add(&sys, &c1);
    ring("r1", &sys);
    printf("add c2\n");
    add(&sys, &c2);
    ring("r2", &sys);
    printf("add c3\n");
    add(&sys, &o3.f);
    ring("r3", &sys);
    printf("add c4\n");
    add(&sys, &c4);
    ring("r4", &sys);
    printf("get_size %d\n", (int)physicssystem_get_size(&sys));
}

static void s_walk(void)
{
    PhysicsSystem sys, s2, s3;
    Fake c1, c2, c4, c6, c7, c8, c9, c10;
    Outer o3;
    float buf[ARR];
    int i;

    printf("[walk]\n");
    install();
    physicssystem_init(&sys);
    g_sys = &sys;
    fake_init(&c1, 1, 3, 0, 0.5f, 0.125f, 1.0f);
    fake_init(&c2, 2, 0, 0, 1.0f, 1.0f, 0.0f);
    outer_init(&o3, 3, 2, 0, -1.5f, 2.0f, -3.0f);
    fake_init(&c4, 4, 1, 0, 3.0f, -0.5f, 7.0f);
    add(&sys, &c1);
    add(&sys, &c2);
    add(&sys, &o3.f);
    add(&sys, &c4);
    ring("r", &sys);

    printf("get_state\n");
    fill(buf, 99.0f);
    arr_reset();
    physicssystem_get_state(&sys, buf);
    dump_buf("buf", buf);

    printf("set_state\n");
    for (i = 0; i < ARR; i++)
        buf[i] = 10.0f + (float)i * 0.5f;
    arr_reset();
    physicssystem_set_state(&sys, buf);
    dump_fake(&c1);
    dump_fake(&c2);
    dump_fake(&o3.f);
    dump_fake(&c4);

    printf("get_derivative\n");
    fill(buf, 99.0f);
    c1.aux = 2.0f;
    o3.f.aux = -4.0f;
    arr_reset();
    physicssystem_get_derivative(&sys, buf);
    dump_buf("buf", buf);

    printf("shrink\n");
    physicssystem_init(&s2);
    g_sys = &s2;
    fake_init(&c6, 6, 2, FK_SHRINK, 1.0f, 0.5f, 2.0f);
    fake_init(&c7, 7, 2, 0, -1.0f, 0.25f, 5.0f);
    add(&s2, &c6);
    add(&s2, &c7);
    fill(buf, 99.0f);
    arr_reset();
    physicssystem_get_derivative(&s2, buf);
    dump_buf("buf", buf);
    fill(buf, 99.0f);
    arr_reset();
    physicssystem_get_derivative(&s2, buf);
    dump_buf("buf", buf);
    ring("r", &s2);

    printf("negative\n");
    physicssystem_init(&s3);
    g_sys = &s3;
    fake_init(&c8, 8, 3, 0, 0.75f, 1.5f, -1.0f);
    fake_init(&c9, 9, -1, 0, 1.0f, 1.0f, 0.0f);
    fake_init(&c10, 10, 2, 0, -2.0f, 0.5f, 3.0f);
    add(&s3, &c8);
    add(&s3, &c9);
    add(&s3, &c10);
    ring("r", &s3);
    fill(buf, 99.0f);
    arr_reset();
    physicssystem_get_state(&s3, buf);
    dump_buf("buf", buf);
    fill(buf, 99.0f);
    arr_reset();
    physicssystem_get_derivative(&s3, buf);
    dump_buf("buf", buf);
    for (i = 0; i < ARR; i++)
        buf[i] = -(float)i;
    arr_reset();
    physicssystem_set_state(&s3, buf);
    dump_fake(&c8);
    dump_fake(&c10);
}

static void s_insert(void)
{
    PhysicsSystem s1, s2, s3;
    Fake c11, c12, c13, c14, c15, c16, c17, c18, c19;
    float buf[ARR];

    printf("[insert]\n");
    install();

    printf("on derivative\n");
    physicssystem_init(&s1);
    g_sys = &s1;
    fake_init(&c11, 11, 2, FK_INSERT_DERIV, 1.0f, 1.0f, 1.0f);
    fake_init(&c12, 12, 1, 0, 2.0f, 0.0f, 4.0f);
    fake_init(&c13, 13, 2, 0, -1.0f, 0.5f, 6.0f);
    c11.pending = &c12;
    add(&s1, &c11);
    add(&s1, &c13);
    fill(buf, 99.0f);
    arr_reset();
    physicssystem_get_derivative(&s1, buf);
    dump_buf("buf", buf);
    ring("r", &s1);

    printf("on getstate\n");
    physicssystem_init(&s2);
    g_sys = &s2;
    fake_init(&c14, 14, 2, FK_INSERT_GETSTATE, 0.5f, 0.25f, 1.0f);
    fake_init(&c15, 15, 0, 0, 1.0f, 1.0f, 9.0f);
    fake_init(&c16, 16, 3, 0, -0.5f, 1.0f, 2.0f);
    c14.pending = &c15;
    add(&s2, &c14);
    add(&s2, &c16);
    ticks(1000u, 29491u, 7u);
    arr_reset();
    physicssystem_integrate_euler(&s2, 0.125f);
    dump_fake(&c14);
    dump_fake(&c15);
    dump_fake(&c16);
    printf("AuxTime %.9g\n", AuxTime);
    ring("r", &s2);

    printf("on aux\n");
    physicssystem_init(&s3);
    g_sys = &s3;
    fake_init(&c17, 17, 1, FK_INSERT_AUX, 1.0f, 0.0f, 3.0f);
    fake_init(&c18, 18, 2, 0, 1.0f, 0.0f, 5.0f);
    fake_init(&c19, 19, 1, 0, 1.0f, 0.0f, -2.0f);
    c17.pending = &c18;
    add(&s3, &c17);
    add(&s3, &c19);
    ticks(50u, 294912u, 0u);
    physicssystem_compute_auxiliaries(&s3);
    printf("AuxTime %.9g\n", AuxTime);
    ring("r", &s3);
}

static void build_mixed(PhysicsSystem *s, Fake *c20, Outer *o21, Fake *c22,
                        Fake *c23)
{
    fake_init(c20, 20, 3, 0, 0.5f, 0.25f, 1.0f);
    outer_init(o21, 21, 2, 0, -0.75f, 1.0f, 4.0f);
    fake_init(c22, 22, -1, 0, 1.0f, 1.0f, 0.0f);
    fake_init(c23, 23, 2, 0, 2.0f, -0.125f, -2.0f);
    add(s, c20);
    add(s, &o21->f);
    add(s, c22);
    add(s, c23);
}

static void s_euler(void)
{
    PhysicsSystem sys, empty;
    SysOuter so;
    Fake c20, c22, c23, e20, e22, e23;
    Outer o21, eo21;
    int k;

    printf("[euler]\n");
    install();
    physicssystem_init(&sys);
    g_sys = &sys;
    build_mixed(&sys, &c20, &o21, &c22, &c23);
    ring("r", &sys);
    ticks(0xfffff000u, 2949120u, 1234u);
    for (k = 0; k < 3; k++) {
        printf("step %d\n", k);
        arr_reset();
        physicssystem_integrate_euler(&sys, 0.0166666675f);
        dump_fake(&c20);
        dump_fake(&o21.f);
        dump_fake(&c22);
        dump_fake(&c23);
        printf("AuxTime %.9g\n", AuxTime);
    }

    printf("derived\n");
    memset(&so, 0, sizeof so);
    so.tag[0] = SYSOUTER_TAG;
    physicssystem_init(&so.sys);
    so.sys._vtable = FAKE_SYS_VT;
    g_sys = &so.sys;
    build_mixed(&so.sys, &e20, &eo21, &e22, &e23);
    ticks(77u, 100000u, 0u);
    for (k = 0; k < 2; k++) {
        printf("step %d\n", k);
        arr_reset();
        physicssystem_integrate_euler(&so.sys, -0.5f);
        dump_fake(&e20);
        dump_fake(&eo21.f);
        dump_fake(&e23);
        printf("AuxTime %.9g\n", AuxTime);
    }

    printf("empty\n");
    physicssystem_init(&empty);
    g_sys = &empty;
    ticks(5u, 3000000u, 0u);
    physicssystem_integrate_euler(&empty, 1.0f);
    printf("AuxTime %.9g\n", AuxTime);
}

static void s_rk(void)
{
    PhysicsSystem sys, s2;
    SysOuter so;
    Fake c20, c22, c23, c30, c31, e20, e22, e23;
    Outer o21, eo21;
    int k;

    printf("[rk]\n");
    install();
    physicssystem_init(&sys);
    g_sys = &sys;
    build_mixed(&sys, &c20, &o21, &c22, &c23);
    ticks(1u, 65536u, 3u);
    for (k = 0; k < 2; k++) {
        printf("step %d\n", k);
        arr_reset();
        physicssystem_integrate_runge_kutta(&sys, 0.0199999996f);
        dump_fake(&c20);
        dump_fake(&o21.f);
        dump_fake(&c23);
        printf("AuxTime %.9g\n", AuxTime);
    }

    printf("dropper\n");
    physicssystem_init(&s2);
    g_sys = &s2;
    fake_init(&c30, 30, 2, FK_DROP, -1.25f, 0.5f, 1.5f);
    fake_init(&c31, 31, 3, 0, 0.75f, -0.25f, -1.0f);
    add(&s2, &c30);
    add(&s2, &c31);
    ticks(9u, 1000u, 0u);
    arr_reset();
    physicssystem_integrate_runge_kutta(&s2, 0.25f);
    dump_fake(&c30);
    dump_fake(&c31);
    ring("r", &s2);

    printf("derived\n");
    memset(&so, 0, sizeof so);
    so.tag[0] = SYSOUTER_TAG;
    physicssystem_init(&so.sys);
    so.sys._vtable = FAKE_SYS_VT;
    g_sys = &so.sys;
    build_mixed(&so.sys, &e20, &eo21, &e22, &e23);
    ticks(123u, 4567u, 89u);
    arr_reset();
    physicssystem_integrate_runge_kutta(&so.sys, 0.5f);
    dump_fake(&e20);
    dump_fake(&eo21.f);
    dump_fake(&e23);
    printf("AuxTime %.9g\n", AuxTime);
}

static void s_aux(void)
{
    PhysicsSystem sys;
    Fake c1, c2;
    static const uint32_t starts[5] = { 0u, 0xfffff000u, 0u, 100u, 7u };
    static const uint32_t steps[5] = { 0u, 0x2000u, 0x80000081u, 0xffffffceu,
                                       0x7fffffffu };
    int k;

    printf("[aux]\n");
    install();
    physicssystem_init(&sys);
    g_sys = &sys;
    fake_init(&c1, 1, 2, 0, 1.0f, 0.0f, 0.5f);
    fake_init(&c2, 2, 1, 0, 1.0f, 0.0f, -3.0f);
    add(&sys, &c1);
    add(&sys, &c2);
    for (k = 0; k < 5; k++) {
        ticks(starts[k], steps[k], 0u);
        physicssystem_compute_auxiliaries(&sys);
        printf("AuxTime %.9g\n", AuxTime);
    }
    physicssystem_resolve_forces(&sys);
    printf("resolve ok %d\n", (int)physicssystem_get_size(&sys));
}

static void s_tables(void)
{
    PhysicsSystem sys;
    Fake c1, c2;
    Fake *h;
    const VtEntry *e;

    printf("[tables]\n");
    install();

    fake_init(&c1, 1, 2, 0, 1.0f, 0.0f, 0.5f);
    c1._vtable = PHYSICSCOMPONENT_VTABLE;
    e = vt_slot(PHYSICSCOMPONENT_VTABLE, PHYSICSCOMPONENT_VT_RESOLVE_FORCES);
    ((PhysicsVoidFn)e->fn)(vt_this(&c1, e));
    e = vt_slot(PHYSICSCOMPONENT_VTABLE,
                PHYSICSCOMPONENT_VT_COMPUTE_AUXILIARIES);
    ((PhysicsVoidFn)e->fn)(vt_this(&c1, e));
    dump_fake(&c1);
    c1._vtable = 0x12345678u;
    e = vt_slot(PHYSICSCOMPONENT_VTABLE, PHYSICSCOMPONENT_VT_DTOR);
    ((PhysicsDtorFn)e->fn)(vt_this(&c1, e), 2);
    printf("dtor vt %08x\n", (unsigned)c1._vtable);
    h = heap_fake(9, 1, 0);
    h->_vtable = 0x12345678u;
    ((PhysicsDtorFn)e->fn)(vt_this(h, e), 3);
    printf("dtor freed\n");

    physicssystem_init(&sys);
    g_sys = &sys;
    fake_init(&c2, 2, 1, 0, 1.0f, 0.0f, 6.0f);
    add(&sys, &c2);
    ticks(0u, 2949120u, 0u);
    e = vt_slot(PHYSICSSYSTEM_VTABLE, PHYSICSSYSTEM_VT_COMPUTE_AUXILIARIES);
    ((PhysicsVoidFn)e->fn)(vt_this(&sys, e));
    printf("AuxTime %.9g\n", AuxTime);
    e = vt_slot(PHYSICSSYSTEM_VTABLE, PHYSICSSYSTEM_VT_RESOLVE_FORCES);
    ((PhysicsVoidFn)e->fn)(vt_this(&sys, e));
    sys._vtable = 0x0badf00du;
    e = vt_slot(PHYSICSSYSTEM_VTABLE, PHYSICSSYSTEM_VT_DTOR);
    ((PhysicsDtorFn)e->fn)(vt_this(&sys, e), 2);
    printf("sys vt %08x\n", (unsigned)sys._vtable);
    ring("r", &sys);
}

static void s_dtor(void)
{
    PhysicsSystem sys;
    PhysicsSystem *hs;
    Fake *h40, *h42, *h43, *h44;
    Outer *h41;

    printf("[dtor]\n");
    install();
    physicssystem_init(&sys);
    g_sys = &sys;
    h40 = heap_fake(40, 1, 0);
    h41 = (Outer *)malloc(sizeof *h41);
    outer_init(h41, 41, 2, 0, 1.0f, 0.0f, 41.0f);
    h41->f.heap = 1;
    h42 = heap_fake(42, 1, FK_UNLINK_NEXT);
    h43 = heap_fake(43, 1, 0);
    h44 = heap_fake(44, 1, 0);
    add(&sys, h40);
    add(&sys, &h41->f);
    add(&sys, h42);
    add(&sys, h43);
    add(&sys, h44);
    ring("r", &sys);
    sys._vtable = FAKE_SYS_VT;
    physicssystem_fini(&sys, 0);
    printf("vt %08x\n", (unsigned)sys._vtable);
    ring("after", &sys);
    free(h43);

    printf("heap\n");
    hs = (PhysicsSystem *)malloc(sizeof *hs);
    physicssystem_init(hs);
    g_sys = hs;
    add(hs, heap_fake(45, 2, 0));
    physicssystem_fini(hs, 1);
    printf("freed\n");
}

static void s_arrays(void)
{
    static const int32_t ns[5] = { -1, 0, 1, 5, 8 };
    float a[8], b[8], o[8];
    int i, k;

    printf("[arrays]\n");
    for (i = 0; i < 8; i++) {
        a[i] = 0.1f * (float)(i + 1);
        b[i] = 3.0f - 0.7f * (float)i;
    }
    for (k = 0; k < 5; k++) {
        printf("n %d\n", (int)ns[k]);
        for (i = 0; i < 8; i++)
            o[i] = 77.0f;
        ArrayMultiply(o, a, 1.5f, ns[k]);
        dump_buf("mul", o);
        for (i = 0; i < 8; i++)
            o[i] = 77.0f;
        ArrayAdd(o, a, b, ns[k]);
        dump_buf("add", o);
        for (i = 0; i < 8; i++)
            o[i] = 77.0f;
        ArrayMultiplyAndAdd(o, a, b, -0.75f, ns[k]);
        dump_buf("madd", o);
    }
    for (i = 0; i < 8; i++)
        o[i] = a[i];
    ArrayMultiplyAndAdd(o, o, b, PHYSICSSYSTEM_RK_THIRD, 8);
    dump_buf("inplace", o);
    for (i = 0; i < 8; i++)
        o[i] = b[i];
    ArrayAdd(o, a, o, 6);
    dump_buf("alias-b", o);
}

static void s_ticker(void)
{
    static const uint32_t pairs[][2] = {
        { 0u, 0u }, { 0u, 1u }, { 0u, 294912u }, { 100u, 50u },
        { 0xfffffff0u, 0x10u }, { 0u, 0x7fffffffu }, { 0u, 0x80000000u },
        { 0u, 0x80000001u }, { 0u, 0x80000003u }, { 0u, 0x80000081u },
        { 0u, 0x80000080u }, { 0u, 0x80000180u }, { 0u, 0xffffffffu },
        { 0u, 0x01000001u }, { 0u, 0x01000003u }, { 5u, 0x03ffffffu },
        { 0u, 0x04000000u }, { 0u, 0x04000005u }, { 1u, 0xfffffe00u },
        { 0x12345678u, 0x9abcdef0u }, { 0u, 2949120u },
    };
    int k;

    printf("[ticker]\n");
    bInitTicker();
    bSetTickerSource(NULL);
    printf("host %u\n", (unsigned)bGetTicker());
    for (k = 0; k < (int)(sizeof pairs / sizeof pairs[0]); k++) {
        float f = bGetTickerDifference(pairs[k][0], pairs[k][1]);
        printf("diff %08x %08x %.9g %08x %u\n", (unsigned)pairs[k][0],
               (unsigned)pairs[k][1], f, fbits(f),
               (unsigned)bGetFixTickerDifference(pairs[k][0], pairs[k][1]));
    }
    ticks(0xfffffffeu, 1u, 0x40000000u);
    for (k = 0; k < 4; k++)
        printf("tick %08x\n", (unsigned)bGetTicker());
    bSetTickerSource(NULL);
    printf("host %u\n", (unsigned)bGetTicker());
}

static void s_p32(void)
{
    int x, y;
    uint32_t h0, hx, hy, hx2;

    printf("[p32]\n");
    p32_reset();
    h0 = p32_of(NULL);
    hx = p32_of(&x);
    hy = p32_of(&y);
    hx2 = p32_of(&x);
    printf("p32 %u %d %d %d %d %d\n", (unsigned)h0, hx == hx2, hx != hy,
           p32_ptr(hx) == (void *)&x, p32_ptr(0) == NULL, hx != 0);
}

int main(void)
{
    s_layout();
    s_add();
    s_walk();
    s_insert();
    s_euler();
    s_rk();
    s_aux();
    s_tables();
    s_dtor();
    s_arrays();
    s_ticker();
    s_p32();
    return 0;
}
