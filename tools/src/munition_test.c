// Harness for tools/munition_check.py: runs the checker's script on
// munition.c -- the helicopter's rockets, smoke bombs and dropped spikes,
// the explosions' handler and the module's init and close -- over
// smokeable.c and smokeableinfo.c, and prints what the model prints for the
// retail image. smokeable_test.c is included whole: its stubs, dumps and
// ops, with the pools and bMalloc renamed so the ones here can take the
// munitions' and hand it the rest. See the checker's docstring.
//
//     munition_test script.txt > out.txt

#define SMOKEABLE_TEST_EXTRA
#define bNewSlotPool smk_bNewSlotPool
#define bSlotOMalloc smk_bSlotOMalloc
#define bMalloc      smk_bMalloc
#include "smokeable_test.c"
#undef bNewSlotPool
#undef bSlotOMalloc
#undef bMalloc

#include "airoute.h"
#include "bvector.h"
#include "car.h"
#include "cop.h"
#include "copmanager.h"
#include "coputil.h"
#include "munition.h"
#include "psychodriver.h"
#include "pursuit.h"
#include "sundraw.h"
#include "trackroute.h"

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *pname,
                        int poolNum);
void      *bSlotOMalloc(BSlotPool *pool);
void      *bMalloc(int size, const char *nm, int flags, int pool);

#define MAX_CARS   16
#define CAR_VTABLE 0x00400200u          // the cars' bodies' table

static _Alignas(16) uint8_t tok_rkp[16], tok_sbp[16], tok_dsp[16];
static _Alignas(16) uint8_t tok_cm[16], tok_smp[16];

// What the image has and the munitions read.
int32_t      bStartGlare;
tCopManager *pCopManager;
void (*gCarDamageWreckFn)(void *damage);
void (*gRealDriverForceEBrakeStopFn)(struct RealDriver *d, float t);
PlayerRequestZoneFn gPlayerRequestZoneFn;
void (*gCopManagerAddSpikeStripFn)(tCopManager *m, const bVector2 *a,
                                   const bVector2 *b, int32_t id, float t);

static World *world;
static Car   *cars[MAX_CARS];
static int    ncars;

// The scripted answers.
static struct { int32_t ret; TrackRoutePoint *pt; } nearq[64];
static int     nearq_n, nearq_i;
static int32_t atanq[64];
static int     atanq_n, atanq_i;

static MunitionEffectsHandler *saved_handler;

// ------------------------------------------------------- pools and memory

static void name_smokeable(Smokeable *s, const char *p, int k)
{
    char f[16];

    snprintf(f, sizeof f, "%s%%d", p);
    namef(s, f, k, 0);
    snprintf(f, sizeof f, "%s%%d.sys", p);
    namef(&s->System, f, k, 0);
    snprintf(f, sizeof f, "%s%%d.tc", p);
    namef(&s->TC, f, k, 0);
    snprintf(f, sizeof f, "%s%%d.wo", p);
    namef(&s->TheWorldObject, f, k, 0);
    snprintf(f, sizeof f, "%s%%d.m", p);
    namef(&s->TheWorldObject.Matrix, f, k, 0);
    snprintf(f, sizeof f, "%s%%d.al", p);
    namef(&s->AnchorEmitterList, f, k, 0);
    snprintf(f, sizeof f, "%s%%d.dl", p);
    namef(&s->DynamicEmitterList, f, k, 0);
}

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *pname,
                        int poolNum)
{
    static const struct {
        const char *name;
        size_t      host;
        int         retail;
        uint8_t    *tok;
    } t[] = {
        { "RocketSlotPool", sizeof(Rocket), 1168, tok_rkp },
        { "SmokeBombSlotPool", sizeof(SmokeBomb), 1152, tok_sbp },
        { "DroppedSpikesSlotPool", sizeof(DroppedSpikes), 1168, tok_dsp },
    };
    size_t i;

    for (i = 0; i < sizeof t / sizeof t[0]; i++)
        if (!strcmp(pname, t[i].name)) {
            printf("  newpool %d %d %s %d\n",
                   slotSize == (int)t[i].host ? t[i].retail : slotSize,
                   numSlots, pname, poolNum);
            return (BSlotPool *)(void *)t[i].tok;
        }
    return smk_bNewSlotPool(slotSize, numSlots, pname, poolNum);
}

void *bSlotOMalloc(BSlotPool *pool)
{
    Smokeable *s;

    if (pool == (BSlotPool *)(void *)tok_rkp) {
        s = block(sizeof(Rocket));
        name_smokeable(s, "RK", count_of('r'));
    } else if (pool == (BSlotPool *)(void *)tok_sbp) {
        s = block(sizeof(SmokeBomb));
        name_smokeable(s, "SB", count_of('b'));
    } else if (pool == (BSlotPool *)(void *)tok_dsp) {
        s = block(sizeof(DroppedSpikes));
        name_smokeable(s, "DS", count_of('d'));
    } else {
        return smk_bSlotOMalloc(pool);
    }
    printf("  omalloc %s -> %s\n", pool_name(pool), sym(s));
    return s;
}

void *bMalloc(int size, const char *nm, int flags, int pool)
{
    void *p;

    if (strcmp(nm, "MunitionEffectsHandler"))
        return smk_bMalloc(size, nm, flags, pool);
    p = block((size_t)size);
    namef(p, "MEH%d", count_of('h'), 0);
    printf("  hmalloc %d %s %d %d -> %s\n",
           size == (int)sizeof(MunitionEffectsHandler) ? 8 : size, nm, flags,
           pool, sym(p));
    return p;
}

void bFree(void *p)
{
    printf("  bfree %s\n", sym(p));
}

// ------------------------------------------------------------------ stubs

void dynamiccollisionbody_backup(CollisionBody *b, float t)
{
    printf("  dynbackup %s %08x\n", sym(b), fb(t));
}

void collision_sound_play_explosion(const bVector3 *pos)
{
    printf("  explosion");
    words(pos, 3);
    printf("\n");
}

int ai_get_nearest_route_point(NearestRoutePointInfo *info,
                               const bVector2 *pos, RoutesToSearch which,
                               int flags, float distanceAround)
{
    int32_t          r = 0;
    TrackRoutePoint *pt = NULL;

    if (nearq_i < nearq_n) {
        r = nearq[nearq_i].ret;
        pt = nearq[nearq_i].pt;
        nearq_i++;
    }
    printf("  nearest %s", sym(pos));
    words(pos, 2);
    printf(" %d %d %08x -> %d %s\n", (int)which, flags, fb(distanceAround),
           (int)r, sym(pt));
    if (r) {
        info->Route = (TrackRoute *)(void *)tok_xp;
        info->Point = pt;
    }
    return r;
}

// The rule: x + len, y - len, z / 2; the fourth lane left.
void bNormalize3To(bVector3 *o, const bVector3 *v, float len)
{
    float x = v->x, y = v->y, z = v->z;

    printf("  normalize %s", sym(v));
    words(v, 4);
    printf(" %08x\n", fb(len));
    o->x = x + len;
    o->y = y - len;
    o->z = z * 0.5f;
}

// The rule: x from a plus s, y from b less s.
void bScaleAdd2(bVector2 *o, const bVector2 *a, const bVector2 *b, float s)
{
    float x = a->x + s, y = b->y - s;

    printf("  scaleadd %s", sym(a));
    words(a, 2);
    words(b, 2);
    printf(" %08x\n", fb(s));
    o->x = x;
    o->y = y;
}

int32_t bATan(float x, float y)
{
    int32_t v = atanq_i < atanq_n
                ? atanq[atanq_i++]
                : (int32_t)(((fb(x) >> 7) ^ (fb(y) >> 3)) & 0xffffu);

    printf("  atan %08x %08x -> %d\n", fb(x), fb(y), (int)v);
    return v;
}

float make_relative_angle(float deg)
{
    float d = deg;

    while (180.0f < d)
        d = d - 360.0f;
    while (d < -180.0f)
        d = d + 360.0f;
    printf("  relangle %08x -> %08x\n", fb(deg), fb(d));
    return d;
}

static void rotate(const char *n, bMatrix4 *o, const bMatrix4 *m,
                   uint16_t bam, int k, float sign)
{
    float r[16];

    memcpy(r, m, sizeof r);
    printf("  %s %s", n, sym(m));
    words(m, 16);
    printf(" %d\n", (int)bam);
    r[k] = r[k] + sign * (float)bam;
    memcpy(o, r, sizeof r);
}

void eRotateY(bMatrix4 *o, const bMatrix4 *m, uint16_t bam)
{
    rotate("roty", o, m, bam, 2, 1.0f);
}

void eRotateZ(bMatrix4 *o, const bMatrix4 *m, uint16_t bam)
{
    rotate("rotz", o, m, bam, 4, -1.0f);
}

static void stub_wreck(void *damage)
{
    printf("  wreck %s\n", sym(damage));
}

static void stub_ebrake(struct RealDriver *d, float t)
{
    printf("  ebrake %s %08x\n", sym(d), fb(t));
}

static int32_t stub_zone(Player *p, int32_t zone, int32_t force, int32_t b2,
                         int32_t b3)
{
    printf("  zone %s %d %d %d %d\n", sym(p), (int)zone, (int)force, (int)b2,
           (int)b3);
    return 1;
}

static void stub_spikes(tCopManager *m, const bVector2 *a, const bVector2 *b,
                        int32_t id, float t)
{
    printf("  spikes %s", sym(m));
    words(a, 2);
    words(b, 2);
    printf(" %d %08x\n", (int)id, fb(t));
}

// The cars' bodies' table: SetToPhysicsMode (112) and ApplyImpulse (128).
static void stub_physmode(void *self, CollisionBody *other)
{
    printf("  physmode %s %s\n", sym(self), sym(other));
}

static void stub_carimpulse(void *self, bVector3 *j, bVector3 *at)
{
    printf("  carimpulse %s", sym(self));
    words(j, 4);
    words(at, 3);
    printf("\n");
}

static VtEntry car_vt[VT_SLOT(128) + 1];

// ------------------------------------------------------------------ cars

// car|ctl|mv|x|y|z|w|wheels|player|damage|finish
static void set_car(Car *c, int k, char **a)
{
    c->TheControlMode = (ControlMode)num(a[0]);
    c->TheMovementMode = (MovementMode)num(a[1]);
    setw(&c->State.Position, a + 2, 4);
    c->State.nWheelsTouchingGround = num(a[6]);
    if (num(a[7])) {
        c->pPlayer = block_fill(16, 0);
        namef(c->pPlayer, "Q%dp", k, 0);
    } else {
        c->pPlayer = NULL;
    }
    if (num(a[8])) {
        c->pCarDamage = block_fill(16, 0);
        namef(c->pCarDamage, "Q%dx", k, 0);
    } else {
        c->pCarDamage = NULL;
    }
    c->pRacingCar->FinishReason = (int16_t)num(a[9]);
}

static void make_car(char **a)
{
    int            k = ncars;
    Car           *c = block_fill(sizeof *c, 0);
    CollisionBody *b = block_fill(sizeof *b, 0);

    if (ncars == MAX_CARS) {
        fprintf(stderr, "too many cars\n");
        exit(2);
    }
    namef(c, "Q%d", k, 0);
    namef(b, "Q%db", k, 0);
    b->_vtable = CAR_VTABLE;
    c->pDynamicCollisionBody = (CarCollisionBody *)(void *)b;
    c->pCarDriver = block_fill(sizeof(PsychoDriver), 0);
    namef(c->pCarDriver, "Q%dd", k, 0);
    c->pRacingCar = block_fill(sizeof(RacingCar), 0);
    namef(c->pRacingCar, "Q%dr", k, 0);
    set_car(c, k, a);
    cars[ncars++] = c;
    world->CarTable[world->TotalNumCars++] = c;
}

static Car *car_ref(const char *s)
{
    int k;

    for (k = 0; k < ncars; k++)
        if (!strcmp(sym(cars[k]), s))
            return cars[k];
    fprintf(stderr, "no such car %s\n", s);
    exit(2);
}

// ------------------------------------------------------------------ dumps

static const struct {
    VtFn        fn;
    const char *name;
} mnames[] = {
#define FN(f) { (VtFn)(f), #f }
    FN(munition_backup), FN(droppedbomb_move),
    FN(smokebomb_move), FN(smokebomb_get_smoke_type),
    FN(smokebomb_on_lifetime_end),
    FN(droppedspikes_move), FN(droppedspikes_consider_impulse),
    FN(droppedspikes_apply_impulse), FN(droppedspikes_get_smoke_type),
    FN(droppedspikes_on_lifetime_end),
    FN(rocket_move), FN(rocket_consider_impulse), FN(rocket_apply_impulse),
    FN(rocket_get_smoke_type), FN(rocket_on_lifetime_end),
#undef FN
};

static const char *mfn_name(VtFn fn)
{
    size_t i;

    for (i = 0; i < sizeof mnames / sizeof mnames[0]; i++)
        if (mnames[i].fn == fn)
            return mnames[i].name;
    return fn_name(fn);
}

static void dump_mvt(void)
{
    static const struct { const char *tag; uint32_t image; } t[] = {
        { "mun", MUNITION_VTABLE }, { "munsys", MUNITION_SYSTEM_VTABLE },
        { "db", DROPPEDBOMB_VTABLE }, { "dbsys", DROPPEDBOMB_SYSTEM_VTABLE },
        { "sb", SMOKEBOMB_VTABLE }, { "sbsys", SMOKEBOMB_SYSTEM_VTABLE },
        { "ds", DROPPEDSPIKES_VTABLE },
        { "dssys", DROPPEDSPIKES_SYSTEM_VTABLE },
        { "rk", ROCKET_VTABLE }, { "rksys", ROCKET_SYSTEM_VTABLE },
    };
    size_t k;
    int    i, n;

    for (k = 0; k < sizeof t / sizeof t[0]; k++) {
        const VtEntry *e = vt_table(t[k].image, &n);

        printf("vt %s", t[k].tag);
        for (i = 0; i < n; i++)
            printf(" %d:%d:%s", 8 * i,
                   e[i].delta == -(int)offsetof(Smokeable, System)
                   ? -RETAIL_SYSTEM_OFFSET : (int)e[i].delta,
                   mfn_name(e[i].fn));
        printf("\n");
    }
}

static void dump_mcreators(void)
{
    int k;

    printf("creators");
    for (k = 0; k < ST_NUM_SMOKEABLE_TYPES; k++) {
        SmokeableCreatorFn f = SmokeableCreators[k];

        printf(" %s", f == NULL ? "0"
                      : f == smokeable_basic_creator ? "basic"
                      : f == rocket_smokeable_creator ? "rocket"
                      : f == smokebomb_smokeable_creator ? "smokebomb"
                      : f == droppedspikes_smokeable_creator ? "spikes"
                      : "?");
    }
    printf("\n");
}

static void dump_mglob(void)
{
    printf("mglob pools %s %s %s handler %s glare %d rke",
           sym(RocketSlotPool), sym(SmokeBombSlotPool),
           sym(DroppedSpikesSlotPool), sym(TheMunitionEffectsHandler),
           (int)bStartGlare);
    tlist(&RocketEmitters);
    printf(" sbe");
    tlist(&SmokeBombEmitters);
    printf(" dse");
    tlist(&DroppedSpikesEmitters);
    if (TheMunitionEffectsHandler != NULL) {
        printf(" list");
        plist(&TheMunitionEffectsHandler->List);
    }
    printf("\n");
}

static const ExplodeParams *params(const char *s)
{
    if (!strcmp(s, "sb"))
        return &SmokeBombExplodeParams;
    if (!strcmp(s, "ds"))
        return &DroppedSpikesExplodeParams;
    return &RocketExplodeParams;
}

// -------------------------------------------------------------------- ops

static int extra_op(char **a, int na)
{
    const char *o = a[0];
    static _Alignas(16) bVector3 v1;
    static _Alignas(16) bMatrix4 mx;

    if (!strcmp(o, "initmun")) {
        printf("initmun\n");
        init_munitions();
    } else if (!strcmp(o, "closemun")) {
        printf("closemun\n");
        close_munitions();
    } else if (!strcmp(o, "mvt")) {
        dump_mvt();
    } else if (!strcmp(o, "mcreators")) {
        dump_mcreators();
    } else if (!strcmp(o, "mglob")) {
        dump_mglob();
    } else if (!strcmp(o, "params")) {
        printf("params %s", a[1]);
        words(params(a[1]), 7);
        printf("\n");
    } else if (!strcmp(o, "car")) {
        make_car(a + 1);
    } else if (!strcmp(o, "carmod")) {
        Car *c = car_ref(a[1]);
        int  k;

        for (k = 0; k < ncars; k++)
            if (cars[k] == c)
                set_car(c, k, a + 2);
    } else if (!strcmp(o, "cd")) {
        Car *c = car_ref(a[1]);

        printf("car %s ebrake %08x\n", a[1],
               fb(((PsychoDriver *)(void *)c->pCarDriver)->EBrakeTimer));
    } else if (!strcmp(o, "colm")) {
        Collision *c = ref(a[1]);

        c->Sample = num(a[2]) ? (struct CollisionSample *)(void *)tok_smp
                              : NULL;
        setw(&c->InitialContactPoint, a + 3, 3);
    } else if (!strcmp(o, "sbnew") || !strcmp(o, "dsnew")
               || !strcmp(o, "rknew")) {
        void *r;

        printf("%s\n", o);
        if (!strcmp(o, "sbnew"))
            r = smokebomb_new(bSlotOMalloc(SmokeBombSlotPool));
        else if (!strcmp(o, "dsnew"))
            r = droppedspikes_new(bSlotOMalloc(DroppedSpikesSlotPool));
        else
            r = rocket_new(bSlotOMalloc(RocketSlotPool));
        printf("  -> %s\n", sym(r));
    } else if (!strcmp(o, "blaunch")) {
        setw(&mx, a + 2, 16);
        setw(&v1, a + 18, 4);
        printf("blaunch %s\n", a[1]);
        droppedbomb_launch(ref(a[1]), &mx, &v1);
    } else if (!strcmp(o, "rlaunch")) {
        setw(&mx, a + 2, 16);
        setw(&v1, a + 18, 4);
        printf("rlaunch %s %s\n", a[1], a[22]);
        rocket_launch(ref(a[1]), &mx, &v1,
                      strcmp(a[22], "0") ? car_ref(a[22]) : NULL);
    } else if (!strcmp(o, "explode")) {
        printf("explode %s %s %s\n", a[1], a[2], a[3]);
        munition_explode_warhead(ref(a[1]), params(a[2]), num(a[3]));
    } else if (!strcmp(o, "belt")) {
        printf("belt %s\n", a[1]);
        droppedspikes_make_spike_belt(ref(a[1]));
    } else if (!strcmp(o, "flat")) {
        munition_get_flat_matrix(ref(a[1]), &mx);
        printf("flat %s", a[1]);
        words(&mx, 16);
        printf("\n");
    } else if (!strcmp(o, "backup")) {
        void          *b = ref(a[1]);
        const VtEntry *e = body_slot(b, COLLISIONBODY_VT_BACKUP);

        printf("backup %s %s\n", a[1], a[2]);
        ((MoveFn)e->fn)(vt_this(b, e), bf(hex(a[2])));
    } else if (!strcmp(o, "lifeend")) {
        void          *b = ref(a[1]);
        const VtEntry *e = body_slot(b, SMOKEABLE_VT_ON_LIFETIME_END);

        printf("lifeend %s\n", a[1]);
        ((VoidFn)e->fn)(vt_this(b, e));
    } else if (!strcmp(o, "smoketype")) {
        void          *b = ref(a[1]);
        const VtEntry *e = body_slot(b, SMOKEABLE_VT_GET_SMOKE_TYPE);

        printf("smoketype %s -> %d\n", a[1], (int)((IntFn)e->fn)(vt_this(b, e)));
    } else if (!strcmp(o, "mdtor") || !strcmp(o, "dbdtor")) {
        printf("%s %s %s\n", o, a[1], a[2]);
        if (!strcmp(o, "mdtor"))
            munition_destroy(ref(a[1]), num(a[2]));
        else
            droppedbomb_destroy(ref(a[1]), num(a[2]));
    } else if (!strcmp(o, "efftick")) {
        printf("efftick %s\n", a[1]);
        munitioneffectshandler_do_timestep(TheMunitionEffectsHandler,
                                           bf(hex(a[1])));
    } else if (!strcmp(o, "addeff")) {
        setw(&mx, a + 2, 16);
        printf("addeff %s\n", a[1]);
        munitioneffectshandler_add_effect(TheMunitionEffectsHandler,
                                          ref(a[1]), &mx);
    } else if (!strcmp(o, "es")) {
        ((AcidEmitter *)ref(a[1]))->State = num(a[2]);
    } else if (!strcmp(o, "addem")) {
        bNode *list = ref(a[1]);
        int    n = num(a[2]), k;

        for (k = 0; k < n; k++) {
            AcidEmitter *e = block(sizeof *e);
            bNode       *tail = list->prev;

            namef(e, "E%d", count_of('E'), 0);
            tail->next = &e->Node;
            list->prev = &e->Node;
            e->Node.prev = tail;
            e->Node.next = list;
        }
    } else if (!strcmp(o, "md")) {
        Munition *m = ref(a[1]);

        printf("mun %s bd %d\n", a[1], (int)m->BackupDone);
    } else if (!strcmp(o, "mds")) {
        DroppedSpikes *s = ref(a[1]);

        printf("spikes %s bd %d deploy %d\n", a[1], (int)s->Base.BackupDone,
               (int)s->DeploySpikes);
    } else if (!strcmp(o, "mdr")) {
        Rocket *r = ref(a[1]);

        printf("rocket %s bd %d target %s yaw %08x\n", a[1],
               (int)r->Base.BackupDone, sym(r->Target), fb(r->Yaw));
    } else if (!strcmp(o, "mf")) {
        Munition *m = ref(a[1]);

        if (!strcmp(a[2], "bd"))
            m->BackupDone = num(a[3]);
        else if (!strcmp(a[2], "deploy"))
            ((DroppedSpikes *)(void *)m)->DeploySpikes = num(a[3]);
        else if (!strcmp(a[2], "target"))
            ((Rocket *)(void *)m)->Target =
                strcmp(a[3], "0") ? car_ref(a[3]) : NULL;
        else if (!strcmp(a[2], "yaw"))
            ((Rocket *)(void *)m)->Yaw = bf(hex(a[3]));
        else {
            fprintf(stderr, "munition field %s\n", a[2]);
            exit(2);
        }
    } else if (!strcmp(o, "tp")) {
        TrackRoutePoint *p = block_fill(sizeof *p, 0);

        namef(p, "TP%d", count_of('T'), 0);
        setw(&p->Position, a + 1, 2);
        setw(&p->Direction, a + 3, 2);
        setw(&p->LeftWidth, a + 5, 1);
        setw(&p->RightWidth, a + 6, 1);
    } else if (!strcmp(o, "near")) {
        nearq[nearq_n].ret = num(a[1]);
        nearq[nearq_n].pt = ref(a[2]);
        nearq_n++;
    } else if (!strcmp(o, "atan")) {
        int i;

        for (i = 1; i < na; i++)
            atanq[atanq_n++] = num(a[i]);
    } else if (!strcmp(o, "glare")) {
        bStartGlare = num(a[1]);
    } else if (!strcmp(o, "hnull")) {
        saved_handler = TheMunitionEffectsHandler;
        TheMunitionEffectsHandler = NULL;
    } else if (!strcmp(o, "hback")) {
        TheMunitionEffectsHandler = saved_handler;
    } else {
        return 0;
    }
    return 1;
}

static void extra_init(void)
{
    car_vt[VT_SLOT(COLLISIONBODY_VT_SET_TO_PHYSICS_MODE)].fn =
        (VtFn)stub_physmode;
    car_vt[VT_SLOT(COLLISIONBODY_VT_APPLY_IMPULSE)].fn = (VtFn)stub_carimpulse;
    vt_install(CAR_VTABLE, car_vt, VT_SLOT(128) + 1);
    munition_install_vtables();
    world = block_fill(sizeof *world, 0);
    name(world, "W");
    pCurrentWorld = world;
    name(tok_rkp, "RKP");
    name(tok_sbp, "SBP");
    name(tok_dsp, "DSP");
    name(tok_cm, "CM");
    name(tok_smp, "SMP");
    name(&RocketEmitters, "RKE");
    name(&SmokeBombEmitters, "SBE");
    name(&DroppedSpikesEmitters, "DSE");
    pCopManager = (tCopManager *)(void *)tok_cm;
    gCarDamageWreckFn = stub_wreck;
    gRealDriverForceEBrakeStopFn = stub_ebrake;
    gPlayerRequestZoneFn = stub_zone;
    gCopManagerAddSpikeStripFn = stub_spikes;
}
