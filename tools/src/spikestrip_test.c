// Harness for tools/spikestrip_check.py: runs the checker's script on
// spikestrip.c -- tSpikeStrip and its belt pieces, and the cop manager's
// AddSpikeStrip and MonitorSpikeBelts -- and on worldobject.c, and prints
// what the model prints for the retail image. See the checker's docstring.
//
//     spikestrip_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "aicarcontroller.h"
#include "bslotpool.h"
#include "car.h"
#include "carcontroller.h"
#include "copmanager.h"
#include "camera.h"
#include "copmgr.h"
#include "coputil.h"
#include "eframe.h"
#include "elight.h"
#include "emath.h"
#include "emodel.h"
#include "eview.h"
#include "eviewmatrix.h"
#include "hudscore.h"
#include "playerzone.h"
#include "pursuit.h"
#include "race.h"
#include "realtime.h"
#include "scenery.h"
#include "scenerycull.h"
#include "spikestrip.h"
#include "topology.h"
#include "vtable.h"
#include "world.h"
#include "worldobject.h"

#define NCARS   6
#define NCOPS   7
#define MAXBLK  64
#define FAKE_VT 0x00500000u
#define BOOST_DELTA 16
#define NVIEWS  2
#define NSOLIDS 4
#define MAXMODELS 2048

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

static uint32_t num(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static uint32_t hex(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 16);
}

// ------------------------------------------------------------ the names

#define MAX_NAMES 4096

static struct {
    const void *p;
    char        name[24];
} names[MAX_NAMES];
static int nnames;

// Frame memory, named by its offset.
static _Alignas(16) uint8_t farena[4096];

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

static const char *sym(const void *p)
{
    uintptr_t u = (uintptr_t)p;
    int       i;

    if (p == NULL)
        return "0";
    if (u == (uintptr_t)0xcdcdcdcdcdcdcdcdull)
        return "cd";
    if ((const uint8_t *)p >= farena
        && (const uint8_t *)p < farena + sizeof farena) {
        static char b[4][24];
        static int  r;

        r = (r + 1) & 3;
        snprintf(b[r], sizeof b[r], "F+%d", (int)((const uint8_t *)p - farena));
        return b[r];
    }
    for (i = nnames - 1; i >= 0; i--)
        if (names[i].p == p)
            return names[i].name;
    return "?";
}

// ---------------------------------------------------- the world it reads

RaceParameters TheRaceParameters;
World         *pCurrentWorld;
float          WorldTimeElapsed;
BSlotPool     *SpikeStripSlotPool;
BSlotPool     *eModelSlotPool;
void (*gEModelInitFn)(eModel *m, uint32_t name_hash);
void (*gEModelDestroyFn)(eModel *m, int32_t flags);
void (*gCopManagerCreatePulloverFn)(tCopManager *m, tPursuit *p,
                                    struct Car *car, int32_t b);
void (*gEModelRenderFn)(eModel *m, bMatrix4 *matrix, void *light,
                        uint32_t flags);
uint8_t  *CurrentBufferPos;
uint8_t  *CurrentBufferEnd;
int32_t   FrameMallocFailed;
uint32_t  FrameMallocFailAmount;

static eView    views[NVIEWS];
static Camera   cams[NVIEWS];
static bMatrix4 wvs[NVIEWS], clips[NVIEWS];
static eSolid   solids[NSOLIDS];
static eView   *cur_view;
static eModel  *models[MAXMODELS];

// The answers GetPixelSize and ClassifyAABB give, in order.
static int32_t pixq[256], clsq[256];
static int     pixq_n, pixq_i, clsq_n, clsq_i;

static uint8_t tok_ssp[16], tok_emp[16], tok_wop[16], tok_pursuit[16];
static uint8_t players[NCARS][16], racers[NCARS][16];

static World           world;
static tCopManager     the_mgr;
static struct tCop     cops[NCOPS];
static Car             cars[NCARS];
static DriverInfo      drivers[NCARS];
static AICarController ctls[NCARS];
static uint32_t        dist_bits[NCARS];
static int32_t         blinking[NCARS];
static int32_t         pursued[NCARS];

// The answers GetVectorOnTrack and DoSegmentsIntersect give, in order.
static uint32_t gvq[256][3];
static int      gvq_n, gvq_i;
static int32_t  dsq[256];
static int      dsq_n, dsq_i;

// --------------------------------------------------------- the blocks

static _Alignas(16) uint8_t heap[1 << 20];
static size_t heap_top;
static int    fill = 0xcd;

static void *block(size_t size)
{
    void *p;

    heap_top = (heap_top + 15) & ~(size_t)15;
    if (heap_top + size > sizeof heap) {
        fprintf(stderr, "heap exhausted\n");
        exit(2);
    }
    p = heap + heap_top;
    heap_top += size;
    memset(p, fill, size);
    return p;
}

static tSpikeStrip *strips[MAXBLK];
static int          nstrips, nmodels, nblocks, nelems, nwos;
static tSpikeStripRenderElement *elems[MAXBLK];
static WorldObject *wos[MAXBLK];

static const char *pool_name(const BSlotPool *p)
{
    if (p == (const void *)tok_ssp)
        return "SSP";
    if (p == (const void *)tok_emp)
        return "EMP";
    if (p == (const void *)tok_wop)
        return "WOP";
    return sym(p);
}

void *bSlotOMalloc(BSlotPool *pool)
{
    char  b[24];
    void *p;

    if (pool == (BSlotPool *)(void *)tok_ssp) {
        tSpikeStrip *s = block(sizeof *s);
        int          k;

        snprintf(b, sizeof b, "S%d", nstrips);
        name(s, b);
        name(&s->Node, b);
        for (k = 0; k < TSPIKESTRIP_MAX_ELEMENTS; k++) {
            WorldObject *w = &s->Elements[k].Base;

            snprintf(b, sizeof b, "S%d.%d", nstrips, k);
            name(&s->Elements[k], b);
            snprintf(b, sizeof b, "S%d.%d.m", nstrips, k);
            name(&w->Matrix, b);
            snprintf(b, sizeof b, "S%d.%d.p", nstrips, k);
            name(&w->Matrix.v3, b);
        }
        snprintf(b, sizeof b, "S%d.start", nstrips);
        name(&s->v2Start, b);
        snprintf(b, sizeof b, "S%d.end", nstrips);
        name(&s->v2End, b);
        strips[nstrips++] = s;
        p = s;
        snprintf(b, sizeof b, "S%d", nstrips - 1);
    } else if (pool == (BSlotPool *)(void *)tok_emp) {
        p = block(sizeof(eModel));
        if (nmodels == MAXMODELS) {
            fprintf(stderr, "too many models\n");
            exit(2);
        }
        models[nmodels] = p;
        snprintf(b, sizeof b, "E%d", nmodels++);
        name(p, b);
    } else {
        p = block(4096);
        snprintf(b, sizeof b, "B%d", nblocks++);
        name(p, b);
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
    printf("  newpool %d %d %s %d\n", slotSize == (int)sizeof(WorldObject)
           ? 96 : -slotSize, numSlots, pname, poolNum);
    return (BSlotPool *)(void *)tok_wop;
}

void bDeleteSlotPool(BSlotPool *pool)
{
    printf("  delpool %s\n", pool_name(pool));
}

static void model_init(eModel *m, uint32_t hash)
{
    printf("  model init %s hash %08x name %08x solid %s\n", sym(m), hash,
           m->NameHash, sym(m->Solid));
}

static void model_destroy(eModel *m, int32_t flags)
{
    printf("  model dtor %s flags %d\n", sym(m), (int)flags);
}

void get_vector_on_track(bVector3 *out, const bVector2 *in)
{
    uint32_t x, y, z;

    if (gvq_i < gvq_n) {
        x = gvq[gvq_i][0];
        y = gvq[gvq_i][1];
        z = gvq[gvq_i][2];
        gvq_i++;
    } else {
        x = fb(in->x);
        y = fb(in->y);
        z = fb(in->x * 0.25f);
    }
    out->x = bf(x);
    out->y = bf(y);
    out->z = bf(z);
    printf("  gvot %s %08x %08x -> %08x %08x %08x\n", sym(in), fb(in->x),
           fb(in->y), x, y, z);
}

static int car_of_pos(const void *p)
{
    int k;

    for (k = 0; k < NCARS; k++)
        if (p == (const void *)&cars[k].State.Position)
            return k;
    return -1;
}

float world_get_distance_to_closest_player_2d(const World *w,
                                              const bVector2 *p)
{
    int k = car_of_pos(p);

    printf("  dist %s %s -> %08x\n", w == &world ? "W" : "?",
           k < 0 ? "?" : sym(&cars[k]), k < 0 ? 0u : dist_bits[k]);
    return k < 0 ? 0.0f : bf(dist_bits[k]);
}

int32_t car_is_blinking(Car *c)
{
    int k = (int)(c - cars);

    printf("  blinking %s -> %d\n", sym(c), (int)blinking[k]);
    return blinking[k];
}

static int popcount(uint32_t v)
{
    int n = 0;

    for (; v; v &= v - 1)
        n++;
    return n;
}

void car_trigger_tire_blow_out(Car *c, int32_t tires)
{
    printf("  blowout %s %d\n", sym(c), (int)tires);
    c->BlownTireBits |= (uint8_t)tires;
    c->NumBlownTires = (uint8_t)popcount(c->BlownTireBits);
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

void eMulMatrix(bMatrix4 *o, const bMatrix4 *m1, const bMatrix4 *m2)
{
    uint32_t a[16], b[16], r[16];
    int      i;

    memcpy(a, m1, 64);
    memcpy(b, m2, 64);
    printf("  emul %s", sym(m1));
    words(b, 16);
    printf("\n");
    for (i = 0; i < 16; i++)
        r[i] = a[i] * 3u + b[15 - i];
    memcpy(o, r, 64);
}

int32_t eview_get_pixel_size_sphere(eView *view, const bVector3 *p, float r)
{
    int32_t v = pixq_i < pixq_n ? pixq[pixq_i++] : 100;

    printf("  pix %s %s", sym(view), sym(p));
    words(p, 3);
    printf(" %08x -> %d\n", fb(r), (int)v);
    return v;
}

eView *eGetCurrentView(void)
{
    printf("  curview -> %s\n", sym(cur_view));
    return cur_view;
}

int32_t scenery_classify_aabb(const bVector4 *min, const bVector4 *max,
                              const bMatrix4 *clip)
{
    int32_t v = clsq_i < clsq_n ? clsq[clsq_i++] : 1;

    printf("  classify %s %s", sym(min), sym(max));
    words(clip, 16);
    printf(" -> %d\n", (int)v);
    return v;
}

int el_setup_light_context(eLightContext *lc, const bMatrix4 *local_world,
                           const bMatrix4 *hack, const bVector4 *eye,
                           eView *view)
{
    printf("  light %s %s", sym(lc), sym(local_world));
    words(local_world, 16);
    printf(" %s", sym(hack));
    words(eye, 4);
    printf(" %s\n", sym(view));
    return 1;
}

static void mrender(eModel *m, bMatrix4 *matrix, void *light, uint32_t flags)
{
    printf("  mrender %s %s", sym(m), sym(matrix));
    words(matrix, 16);
    printf(" %s %d\n", sym(light), (int)flags);
}

int32_t do_segments_intersect(const bVector2 *p, const bVector2 *d,
                              const bVector2 *q, const bVector2 *e)
{
    int32_t v = dsq_i < dsq_n ? dsq[dsq_i++] : 0;

    printf("  dsi %08x %08x %08x %08x %08x %08x %08x %08x -> %d\n",
           fb(p->x), fb(p->y), fb(d->x), fb(d->y), fb(q->x), fb(q->y),
           fb(e->x), fb(e->y), (int)v);
    return v;
}

int32_t player_request_zone(struct Player *p, int32_t zone, int32_t force,
                            int32_t sound, int32_t muffle)
{
    printf("  zone %s %d %d %d %d\n", sym(p), (int)zone, (int)force,
           (int)sound, (int)muffle);
    return 0;
}

void player_start_score(struct Player *p, int32_t scoring)
{
    printf("  score %s %d\n", sym(p), (int)scoring);
}

tPursuit *copmanager_is_being_pursued(tCopManager *m, struct Car *c)
{
    int k = (int)(c - cars);

    printf("  pursued %s %s -> %d\n", sym(m), sym(c), (int)pursued[k]);
    return pursued[k] ? (tPursuit *)(void *)tok_pursuit : NULL;
}

static void create_pullover(tCopManager *m, tPursuit *p, struct Car *car,
                            int32_t b)
{
    printf("  pullover %s %s %s %d\n", sym(m), sym(p), sym(car), (int)b);
}

static void boost(void *self, float f)
{
    printf("  boost %s %08x\n", sym(self), fb(f));
}

static VtEntry boost_vt[VT_SLOT(CARCONTROLLER_VT_FORCE_BOOST) + 1];

// --------------------------------------------------------------- dumps

static void dump_list(void)
{
    const tPursuitNode *l = &the_mgr.SpikeStripList, *n;
    const bNode        *w;
    int                 i = 0;

    printf("slist");
    for (n = l->Next; n != l && i < 64; n = n->Next, i++)
        printf(" %s<%s", sym(n), sym(n->Prev));
    printf(" | %s<%s\n", sym(l->Next), sym(l->Prev));
    printf("wolist");
    i = 0;
    for (w = WorldObjectList.next; w != &WorldObjectList && i < 400;
         w = w->next, i++)
        printf(" %s<%s", sym(w), sym(w->prev));
    printf(" | %s<%s\n", sym(WorldObjectList.next), sym(WorldObjectList.prev));
}

static void dump_wo(const WorldObject *o)
{
    printf(" next %s prev %s model %s en %08x light %08x pad", sym(o->Node.next),
           sym(o->Node.prev), sym(o->pModel), (uint32_t)o->Enabled,
           (uint32_t)o->AddLighting);
    words(o->_pad20, 3);
    printf(" m");
    words(&o->Matrix, 16);
}

static void dump_elem(const tSpikeStripRenderElement *e)
{
    printf("el %s", sym(e));
    dump_wo(&e->Base);
    printf(" vptr %08x pad", e->vptr);
    words(e->_pad100, 3);
    printf("\n");
}

static void dump_strip(const tSpikeStrip *s)
{
    int k;

    printf("strip %s vptr %08x next %s prev %s start %08x %08x end %08x %08x"
           " id %d blink %d timer %08x life %08x n %d pad", sym(s), s->vptr,
           sym(s->Node.Next), sym(s->Node.Prev), fb(s->v2Start.x),
           fb(s->v2Start.y), fb(s->v2End.x), fb(s->v2End.y),
           (int)s->nRoadBlockID, (int)s->bIsBlinking, fb(s->fBlinkTimer),
           fb(s->fLifetime), (int)s->nNumElements);
    words(s->_pad44, 1);
    printf(" tail");
    words(s->_pad2292, 3);
    printf("\n");
    for (k = 0; k < TSPIKESTRIP_MAX_ELEMENTS; k++)
        dump_elem(&s->Elements[k]);
}

static void dump_cars(void)
{
    int k;

    for (k = 0; k < NCARS; k++)
        printf("car %s blown %02x n %02x act %d pot %08x\n", sym(&cars[k]),
               cars[k].BlownTireBits, cars[k].NumBlownTires,
               (int)ctls[k].ForceCurrentAction, fb(ctls[k].PullOverTimeout));
}

// ----------------------------------------------------------------- ops

static void setf(float *dst, char **a, int n)
{
    int i;

    for (i = 0; i < n; i++)
        dst[i] = bf(hex(a[i]));
}

static void car_field(Car *c, int k, char **a)
{
    const char *f = a[0];

    if (!strcmp(f, "type")) {
        drivers[k].TheDriverType = (DriverType)num(a[1]);
    } else if (!strcmp(f, "player")) {
        c->pPlayer = num(a[1]) ? (Player *)(void *)players[k] : NULL;
    } else if (!strcmp(f, "racing")) {
        c->pRacingCar = num(a[1]) ? (RacingCar *)(void *)racers[k] : NULL;
    } else if (!strcmp(f, "ctl")) {
        c->pCarController = num(a[1]) ? &ctls[k].Base : NULL;
    } else if (!strcmp(f, "pos")) {
        c->State.Position.x = bf(hex(a[1]));
        c->State.Position.y = bf(hex(a[2]));
        c->State.Position.z = bf(hex(a[3]));
    } else if (!strcmp(f, "vel")) {
        c->State.Velocity.x = bf(hex(a[1]));
        c->State.Velocity.y = bf(hex(a[2]));
        c->State.Velocity.z = bf(hex(a[3]));
    } else if (!strcmp(f, "body")) {
        setf(&c->State.BodyMatrix.v0.x, a + 1, 4);
        setf(&c->State.BodyMatrix.v1.x, a + 5, 4);
        setf(&c->State.BodyMatrix.v2.x, a + 9, 4);
    } else if (!strcmp(f, "wheel")) {
        bMatrix4 *m = &c->State.WheelMatrix[num(a[1])];

        setf(&m->v0.x, a + 2, 4);
        setf(&m->v1.x, a + 6, 4);
        setf(&m->v2.x, a + 10, 4);
        setf(&m->v3.x, a + 14, 4);
    } else if (!strcmp(f, "touch")) {
        c->State.WheelTouchingGround[num(a[1])] = (int8_t)num(a[2]);
    } else if (!strcmp(f, "fwd")) {
        c->State.ForwardSpeed = bf(hex(a[1]));
    } else if (!strcmp(f, "blown")) {
        c->BlownTireBits = (uint8_t)num(a[1]);
    } else if (!strcmp(f, "nblown")) {
        c->NumBlownTires = (uint8_t)num(a[1]);
    } else if (!strcmp(f, "dist")) {
        dist_bits[k] = hex(a[1]);
    } else if (!strcmp(f, "blinking")) {
        blinking[k] = (int32_t)num(a[1]);
    } else if (!strcmp(f, "pursued")) {
        pursued[k] = (int32_t)num(a[1]);
    } else if (!strcmp(f, "act")) {
        ctls[k].ForceCurrentAction = (AIActionType)num(a[1]);
    } else if (!strcmp(f, "pot")) {
        ctls[k].PullOverTimeout = bf(hex(a[1]));
    } else {
        fprintf(stderr, "unknown car field %s\n", f);
        exit(2);
    }
}

static void vec2(bVector2 *v, char **a)
{
    v->x = bf(hex(a[0]));
    v->y = bf(hex(a[1]));
}

static void op(char **a, int na)
{
    const char *o = a[0];
    tCopManager *m = &the_mgr;
    int          i;

    (void)na;
    if (!strcmp(o, "wte")) {
        WorldTimeElapsed = bf(hex(a[1]));
    } else if (!strcmp(o, "beacop")) {
        TheRaceParameters.BeACop = (int32_t)num(a[1]);
    } else if (!strcmp(o, "ncars")) {
        world.TotalNumCars = (int32_t)num(a[1]);
    } else if (!strcmp(o, "table")) {
        world.CarTable[num(a[1])] = &cars[num(a[2])];
    } else if (!strcmp(o, "copidx")) {
        m->nPlayerCopIndex = (int32_t)num(a[1]);
    } else if (!strcmp(o, "diff")) {
        m->nDifficultyLevel = (int32_t)num(a[1]);
    } else if (!strcmp(o, "cop")) {
        int i = (int)num(a[1]);

        m->Cops[i] = &cops[i];
        cops[i].pMyCar = &cars[num(a[2])];
    } else if (!strcmp(o, "cf")) {
        int k = (int)num(a[1]);

        car_field(&cars[k], k, a + 2);
    } else if (!strcmp(o, "gv")) {
        gvq[gvq_n][0] = hex(a[1]);
        gvq[gvq_n][1] = hex(a[2]);
        gvq[gvq_n][2] = hex(a[3]);
        gvq_n++;
    } else if (!strcmp(o, "ds")) {
        dsq[dsq_n++] = (int32_t)num(a[1]);
    } else if (!strcmp(o, "fill")) {
        fill = (int)hex(a[1]);
    } else if (!strcmp(o, "dsclear")) {
        dsq_n = dsq_i = 0;
    } else if (!strcmp(o, "mreset")) {
        m->SpikeStripList.Next = m->SpikeStripList.Prev = &m->SpikeStripList;
    } else if (!strcmp(o, "initwo")) {
        printf("initwo\n");
        init_world_objects();
        printf("  pool %s\n", pool_name(WorldObjectSlotPool));
    } else if (!strcmp(o, "closewo")) {
        printf("closewo\n");
        close_world_objects();
        printf("  pool %s\n", pool_name(WorldObjectSlotPool));
    } else if (!strcmp(o, "add")) {
        bVector2 s, e;

        vec2(&s, a + 1);
        vec2(&e, a + 3);
        printf("add\n");
        copmanager_add_spike_strip(m, &s, &e, (int32_t)num(a[5]),
                                   bf(hex(a[6])));
    } else if (!strcmp(o, "init")) {
        bVector2 s, e;

        vec2(&s, a + 2);
        vec2(&e, a + 4);
        printf("init S%d\n", (int)num(a[1]));
        tspikestrip_init(strips[num(a[1])], &s, &e, (int32_t)num(a[6]),
                         bf(hex(a[7])));
    } else if (!strcmp(o, "monitor")) {
        printf("monitor\n");
        copmanager_monitor_spike_belts(m);
    } else if (!strcmp(o, "update")) {
        int32_t r;

        printf("update S%d\n", (int)num(a[1]));
        r = tspikestrip_update(strips[num(a[1])]);
        printf("  -> %d\n", (int)r);
    } else if (!strcmp(o, "poof")) {
        printf("poof S%d\n", (int)num(a[1]));
        tspikestrip_blink_blink_poof(strips[num(a[1])]);
    } else if (!strcmp(o, "dflt")) {
        tSpikeStrip *s;

        printf("dflt\n");
        s = bSlotOMalloc((BSlotPool *)(void *)tok_ssp);
        dump_strip(tspikestrip_construct_default(s));
    } else if (!strcmp(o, "dtor")) {
        tSpikeStrip   *s = strips[num(a[1])];
        const VtEntry *v = vt_slot(s->vptr, TSPIKESTRIP_VT_DTOR);

        printf("dtor S%d %d\n", (int)num(a[1]), (int)num(a[2]));
        ((void (*)(void *, int32_t))v->fn)(vt_this(s, v), (int32_t)num(a[2]));
    } else if (!strcmp(o, "elem")) {
        char b[16];
        tSpikeStripRenderElement *e = block(sizeof *e);

        snprintf(b, sizeof b, "X%d", nelems);
        name(e, b);
        snprintf(b, sizeof b, "X%d.m", nelems);
        name(&e->Base.Matrix, b);
        snprintf(b, sizeof b, "X%d.p", nelems);
        name(&e->Base.Matrix.v3, b);
        elems[nelems++] = e;
        printf("elem %s\n", sym(e));
        tspikestriprenderelement_construct(e);
    } else if (!strcmp(o, "edel")) {
        tSpikeStripRenderElement *e = elems[num(a[1])];
        const VtEntry *v = vt_slot(e->vptr, TSPIKESTRIPRENDERELEMENT_VT_DTOR);

        printf("edel X%d %d\n", (int)num(a[1]), (int)num(a[2]));
        ((void (*)(void *, int32_t))v->fn)(vt_this(e, v), (int32_t)num(a[2]));
    } else if (!strcmp(o, "wo")) {
        // wo|hash|light|16 words, or wo|hash|light|none
        char         b[16];
        WorldObject *w = block(sizeof *w);
        static _Alignas(16) bMatrix4 mx;
        const bMatrix4 *mp = NULL;

        snprintf(b, sizeof b, "O%d", nwos);
        name(w, b);
        snprintf(b, sizeof b, "O%d.m", nwos);
        name(&w->Matrix, b);
        snprintf(b, sizeof b, "O%d.p", nwos);
        name(&w->Matrix.v3, b);
        wos[nwos++] = w;
        if (strcmp(a[3], "none")) {
            setf(&mx.v0.x, a + 3, 16);
            mp = &mx;
        }
        printf("wo %s\n", sym(w));
        worldobject_construct(w, hex(a[1]), mp, (int32_t)num(a[2]));
    } else if (!strcmp(o, "wonull")) {
        wos[num(a[1])]->pModel = NULL;
    } else if (!strcmp(o, "wodel")) {
        printf("wodel O%d %d\n", (int)num(a[1]), (int)num(a[2]));
        worldobject_destruct(wos[num(a[1])], (int32_t)num(a[2]));
    } else if (!strcmp(o, "list")) {
        dump_list();
    } else if (!strcmp(o, "strip")) {
        dump_strip(strips[num(a[1])]);
    } else if (!strcmp(o, "edump")) {
        dump_elem(elems[num(a[1])]);
    } else if (!strcmp(o, "wdump")) {
        printf("wo %s", sym(wos[num(a[1])]));
        dump_wo(wos[num(a[1])]);
        printf("\n");
    } else if (!strcmp(o, "cars")) {
        dump_cars();
    } else if (!strcmp(o, "view")) {
        int k = (int)num(a[1]);

        cams[k].CurrentKey.Position.x = bf(hex(a[2]));
        cams[k].CurrentKey.Position.y = bf(hex(a[3]));
        cams[k].CurrentKey.Position.z = bf(hex(a[4]));
        setf(&clips[k].v0.x, a + 5, 16);
    } else if (!strcmp(o, "curview")) {
        cur_view = &views[num(a[1])];
    } else if (!strcmp(o, "frame")) {
        CurrentBufferPos = farena + num(a[1]);
        CurrentBufferEnd = CurrentBufferPos + num(a[2]);
        FrameMallocFailed = (int32_t)num(a[3]);
        FrameMallocFailAmount = num(a[4]);
    } else if (!strcmp(o, "fdump")) {
        printf("frame pos %d end %d failed %d amount %u\n",
               (int)(CurrentBufferPos - farena),
               (int)(CurrentBufferEnd - farena), (int)FrameMallocFailed,
               FrameMallocFailAmount);
    } else if (!strcmp(o, "msolid")) {
        int s = (int)num(a[2]);

        ((eModel *)wos[num(a[1])]->pModel)->Solid
            = s >= 0 ? (void *)&solids[s] : NULL;
    } else if (!strcmp(o, "allsolid")) {
        for (i = 0; i < nmodels; i++)
            models[i]->Solid = &solids[num(a[1])];
    } else if (!strcmp(o, "pix")) {
        pixq[pixq_n++] = (int32_t)num(a[1]);
    } else if (!strcmp(o, "cls")) {
        clsq[clsq_n++] = (int32_t)num(a[1]);
    } else if (!strcmp(o, "wen")) {
        wos[num(a[1])]->Enabled = (int32_t)num(a[2]);
    } else if (!strcmp(o, "render")) {
        printf("render O%d V%d\n", (int)num(a[1]), (int)num(a[2]));
        worldobject_render(wos[num(a[1])], &views[num(a[2])]);
    } else if (!strcmp(o, "renderall")) {
        printf("renderall V%d\n", (int)num(a[1]));
        render_world_objects(&views[num(a[1])]);
    } else {
        fprintf(stderr, "unknown op %s\n", o);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[1 << 16];
    FILE       *f;
    int         i, k;
    char        b[16];

    if (argc != 2) {
        fprintf(stderr, "usage: spikestrip_test script.txt\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    pCurrentWorld = &world;
    SpikeStripSlotPool = (BSlotPool *)(void *)tok_ssp;
    eModelSlotPool = (BSlotPool *)(void *)tok_emp;
    gEModelInitFn = model_init;
    gEModelDestroyFn = model_destroy;
    gCopManagerCreatePulloverFn = create_pullover;
    gEModelRenderFn = mrender;
    for (i = 0; i < NVIEWS; i++) {
        views[i].pCamera = &cams[i];
        views[i].WorldViewMatrix = &wvs[i];
        views[i].WorldScreenClipMatrix = &clips[i];
        snprintf(b, sizeof b, "V%d", i);
        name(&views[i], b);
        snprintf(b, sizeof b, "K%d", i);
        name(&cams[i], b);
        snprintf(b, sizeof b, "V%d.wv", i);
        name(&wvs[i], b);
        snprintf(b, sizeof b, "V%d.clip", i);
        name(&clips[i], b);
    }
    for (i = 0; i < NSOLIDS; i++) {
        snprintf(b, sizeof b, "L%d", i);
        name(&solids[i], b);
        snprintf(b, sizeof b, "L%d.min", i);
        name(&solids[i].AABBMin, b);
        snprintf(b, sizeof b, "L%d.max", i);
        name(&solids[i].AABBMax, b);
    }
    the_mgr.SpikeStripList.Next = the_mgr.SpikeStripList.Prev
        = &the_mgr.SpikeStripList;
    name(&the_mgr, "M");
    name(&the_mgr.SpikeStripList, "M.sl");
    name(&WorldObjectList, "WOL");
    name(tok_pursuit, "PU");
    for (i = 0; i < NCARS; i++) {
        snprintf(b, sizeof b, "A%d", i);
        name(&cars[i], b);
        snprintf(b, sizeof b, "P%d", i);
        name(players[i], b);
        snprintf(b, sizeof b, "C%d", i);
        name(&ctls[i], b);
        snprintf(b, sizeof b, "C%d+%d", i, BOOST_DELTA);
        name((char *)&ctls[i] + BOOST_DELTA, b);
        for (k = 0; k < 4; k++) {
            snprintf(b, sizeof b, "A%d.w%d", i, k);
            name(&cars[i].State.WheelMatrix[k], b);
        }
        cars[i].MyDriver = &drivers[i];
        cars[i].pCarController = &ctls[i].Base;
        ctls[i].Base._vtable = FAKE_VT;
    }
    boost_vt[VT_SLOT(CARCONTROLLER_VT_FORCE_BOOST)].delta = BOOST_DELTA;
    boost_vt[VT_SLOT(CARCONTROLLER_VT_FORCE_BOOST)].fn = (VtFn)boost;
    vt_install(FAKE_VT, boost_vt,
               (int)(sizeof boost_vt / sizeof boost_vt[0]));
    spikestrip_install_vtables();
    while (fgets(line, sizeof line, f) != NULL) {
        char *a[40], *s = line;
        int   na = 0;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        while (na < 40) {
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
