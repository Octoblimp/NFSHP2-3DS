// aisnap_test -- the harness of tools/aisnap_check.py (TASKS 72c): the
// replay's DoSnapshots for the drivers, the AI, the controllers, the
// splines and the movers, over a script.
//
// The same shape as carsnap_test.c, which it copies the ops of:
// tools/aisnap_check.py writes each record's field table in at the marker
// below -- name, host offset, host size, kind -- from the port's headers,
// so a script line names a field and each side writes and dumps it at its
// own offset. A pointer prints as the object and field it points into. The
// model (retail's code in mipsemu) reads the same script and must print
// the same lines.
//
// Recorded here, as the model's stubs print them: a recording vtable (the
// controllers' drivers, the RigidBody's ComputeAuxiliaries) and the new
// AIAction, a slot from the pool that prints as N0, N1 and so on. What the
// linked files reach outside the snapshots comes from aisnap_stubs.c and
// aisnap_stubdata.c, which `aisnap_check.py --stubs` writes; each of those
// functions stops the run.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "aerodynamics.h"
#include "aiaction.h"
#include "aiactions.h"
#include "aicarcontroller.h"
#include "aidriver.h"
#include "airoute.h"
#include "average.h"
#include "beltmover.h"
#include "bslotpool.h"
#include "car.h"
#include "carcontroller.h"
#include "cardriver.h"
#include "copdriver.h"
#include "copmanager.h"
#include "drivetarget.h"
#include "drivingchoice.h"
#include "drivinglocation.h"
#include "mellowmover.h"
#include "nearbycar.h"
#include "p32.h"
#include "physcomp.h"
#include "physicscar.h"
#include "player.h"
#include "psychodriver.h"
#include "quickspline.h"
#include "realcontroller.h"
#include "realdriver.h"
#include "replay.h"
#include "rigidbody.h"
#include "spline.h"
#include "trackroute.h"
#include "trafficdriver.h"
#include "vtable.h"
#include "wheel.h"
#include "world.h"

typedef struct CsField {
    const char *name;
    size_t      off, size;
    char        kind;           // R raw, P pointer, V vptr
} CsField;

typedef struct CsClass {
    const char    *name;
    size_t         size;
    const CsField *f;
    int            n;
} CsClass;

// An action's slot from the pool; the generated head asserts each fits.
#define ACTION_SLOT 1024

// @FIELDS@

#ifndef CS_GENERATED
#error "built from tools/aisnap_check.py, which writes the field tables in"
#endif

#define REC_IMAGE   0x7e000000u
#define MAX_OBJS    1024

typedef struct Obj {
    char           id[24];
    uint8_t       *base;
    const CsClass *cls;         // NULL: bytes
    int            n;
    size_t         stride, size;
} Obj;

static Obj            objs[MAX_OBJS];
static int            nobjs;
static ReplaySnapshot snap;
static int            nactions;

static const struct { const char *name; uint32_t image; } vts[] = {
    {"rec", REC_IMAGE},
    {"CarDriver", CARDRIVER_VTABLE},
    {"PsychoDriver", PSYCHODRIVER_VTABLE},
    {"RealDriver", REALDRIVER_VTABLE},
    {"AIPlan", AIPLAN_VTABLE},
    {"AIAction", AIACTION_VTABLE},
    {"Pass", AIPASS_VTABLE},
    {"AvoidCars", AIAVOIDCARS_VTABLE},
    {"Draft", AIDRAFT_VTABLE},
    {"Block", AIBLOCK_VTABLE},
    {"NudgeCar", AINUDGECAR_VTABLE},
    {"JustDrive", AIJUSTDRIVE_VTABLE},
    {"PullOver", AIPULLOVER_VTABLE},
    {"GetUnstuck", AIGETUNSTUCK_VTABLE},
    {"AvoidRoadBlock", AIAVOIDROADBLOCK_VTABLE},
    {"IJustGotHit", AIIJUSTGOTHIT_VTABLE},
    {"AccidentRecovery", AIACCIDENTRECOVERY_VTABLE},
};

static void die(const char *what, const char *arg)
{
    fprintf(stderr, "aisnap_test: %s %s\n", what, arg);
    exit(2);
}

static uint32_t vt_image(const char *name)
{
    size_t i;

    for (i = 0; i < sizeof vts / sizeof vts[0]; i++)
        if (!strcmp(vts[i].name, name))
            return vts[i].image;
    die("no table", name);
    return 0;
}

static const char *vt_name(uint32_t image)
{
    static char buf[16];
    size_t i;

    for (i = 0; i < sizeof vts / sizeof vts[0]; i++)
        if (vts[i].image == image)
            return vts[i].name;
    snprintf(buf, sizeof buf, "%08x", (unsigned)image);
    return buf;
}

// ---------------------------------------------------------------- objects

static Obj *add(const char *id, void *base, const CsClass *cls, int n,
                size_t stride)
{
    Obj *o;
    int i;

    if (nobjs == MAX_OBJS)
        die("too many objects at", id);
    for (i = 0; i < nobjs; i++)
        if (!strcmp(objs[i].id, id))
            die("object made twice:", id);
    o = &objs[nobjs++];
    snprintf(o->id, sizeof o->id, "%s", id);
    o->base = base;
    o->cls = cls;
    o->n = n;
    o->stride = stride;
    o->size = stride * (size_t)n;
    return o;
}

static const CsClass *find_class(const char *name)
{
    int i;

    for (i = 0; i < CS_NCLASSES; i++)
        if (!strcmp(cs_classes[i].name, name))
            return &cs_classes[i];
    die("no class", name);
    return NULL;
}

static Obj *find_obj(const char *id)
{
    int i;

    for (i = 0; i < nobjs; i++)
        if (!strcmp(objs[i].id, id))
            return &objs[i];
    die("no object", id);
    return NULL;
}

// `id` or `id[i]`: the object and the element.
static uint8_t *ref(const char *r, Obj **out)
{
    char id[32];
    const char *b = strchr(r, '[');
    int i = 0;
    Obj *o;

    if (b) {
        snprintf(id, sizeof id, "%.*s", (int)(b - r), r);
        i = atoi(b + 1);
    } else {
        snprintf(id, sizeof id, "%s", r);
    }
    o = find_obj(id);
    if (i >= o->n)
        die("past the end:", r);
    *out = o;
    return o->base + (size_t)i * o->stride;
}

static const CsField *find_field(const CsClass *c, const char *path)
{
    int i;

    if (c == NULL)
        die("a field of bytes:", path);
    for (i = 0; i < c->n; i++)
        if (!strcmp(c->f[i].name, path))
            return &c->f[i];
    die("no field", path);
    return NULL;
}

// A field's offset, or a nested record's: its first field's.
static size_t path_off(const CsClass *c, const char *path)
{
    size_t n = strlen(path), best = (size_t)-1;
    int i;

    for (i = 0; i < c->n; i++) {
        const char *f = c->f[i].name;

        if (!strcmp(f, path))
            return c->f[i].off;
        if (!strncmp(f, path, n) && (f[n] == '.' || f[n] == '[')
            && c->f[i].off < best)
            best = c->f[i].off;
    }
    if (best == (size_t)-1)
        die("no field", path);
    return best;
}

static const char *label(const void *p)
{
    static char bufs[8][160];
    static int k;
    char *out = bufs[k++ & 7];
    const uint8_t *q = p;
    int i, j;

    if (p == NULL)
        return "0";
    if (p == (const void *)&snap)
        return "snap";
    for (i = 0; i < nobjs; i++) {
        const Obj *o = &objs[i];
        size_t off, e, el;
        char name[48];

        if (q < o->base || q >= o->base + o->size)
            continue;
        off = (size_t)(q - o->base);
        el = off / o->stride;
        e = off % o->stride;
        if (o->n > 1)
            snprintf(name, sizeof name, "%s[%zu]", o->id, el);
        else
            snprintf(name, sizeof name, "%s", o->id);
        if (e == 0) {
            snprintf(out, 160, "%s", name);
            return out;
        }
        if (o->cls) {
            for (j = 0; j < o->cls->n; j++) {
                const CsField *f = &o->cls->f[j];

                if (f->off <= e && e < f->off + f->size) {
                    if (e == f->off)
                        snprintf(out, 160, "%s.%s", name, f->name);
                    else
                        snprintf(out, 160, "%s.%s+%zu", name, f->name,
                                 e - f->off);
                    return out;
                }
            }
        }
        snprintf(out, 160, "%s+%zu", name, e);
        return out;
    }
    return "?";
}

static int in_stack(const void *p)
{
    char probe;
    uintptr_t h = (uintptr_t)&probe, q = (uintptr_t)p;

    return q < h + 0x40000 && q + 0x40000 > h;
}

static const char *cstr(const void *p)
{
    if (p == NULL)
        return "-";
    if (in_stack(p))
        return "<stack>";
    return p;
}

// The live section: its depth and name.
static const char *where(void)
{
    static char buf[96];
    int d = snap.CurrentSectionDepth;

    if (d < 0) {
        snprintf(buf, sizeof buf, "depth=%d top=-", d);
    } else {
        uint32_t h = snap.SectionInfo[d].Name;

        snprintf(buf, sizeof buf, "depth=%d top=%s", d,
                 h ? (const char *)p32_ptr(h) : "-");
    }
    return buf;
}

// --------------------------------------------------------------- recorders

static void rec_log(int slot, void *self, void *a1)
{
    printf("rec vt%d this=%s", slot, label(self));
    if (slot == 16 || slot == 24)
        printf(" s=%s", a1 == (void *)&snap ? "snap" : "?");
    printf(" %s\n", where());
}

#define REC(n) \
    static void rec_##n(void *self, void *a1) { rec_log(8 * (n), self, a1); }
REC(1)  REC(2)  REC(3)  REC(4)  REC(5)  REC(6)  REC(7)  REC(8)
REC(9)  REC(10) REC(11) REC(12) REC(13) REC(14) REC(15) REC(16)
REC(17) REC(18) REC(19) REC(20) REC(21) REC(22) REC(23) REC(24)
REC(25) REC(26) REC(27) REC(28) REC(29) REC(30) REC(31)
#undef REC

#define E(n) { 0, 0, (VtFn)rec_##n }
static const VtEntry rec_vt[32] = {
    { 0, 0, NULL }, E(1), E(2), E(3), E(4), E(5), E(6), E(7), E(8), E(9),
    E(10), E(11), E(12), E(13), E(14), E(15), E(16), E(17), E(18), E(19),
    E(20), E(21), E(22), E(23), E(24), E(25), E(26), E(27), E(28), E(29),
    E(30), E(31),
};
#undef E

// The pool's slot, for aiaction_new: a block of bytes until a dumpa gives
// it the class of the action it became.
void *bSlotOMalloc(BSlotPool *pool)
{
    char id[16];
    void *p = calloc(1, ACTION_SLOT);

    (void)pool;
    snprintf(id, sizeof id, "N%d", nactions++);
    add(id, p, NULL, 1, ACTION_SLOT);
    return p;
}

// The clock's globals, which the timer op sets; realtime.c would bring the
// joylog in behind it.
int32_t WorldTimer;
int32_t WorldLoopCounter;
float   WorldTimeElapsed;

// ------------------------------------------------------------------ dumps

static void hex(const uint8_t *p, size_t n)
{
    size_t i;

    for (i = 0; i < n; i++)
        printf("%02x", p[i]);
}

static void dump_obj(const Obj *o)
{
    int i, j;

    for (i = 0; i < o->n; i++) {
        const uint8_t *base = o->base + (size_t)i * o->stride;
        char name[48];

        if (o->n > 1)
            snprintf(name, sizeof name, "%s[%d]", o->id, i);
        else
            snprintf(name, sizeof name, "%s", o->id);
        if (o->cls == NULL) {
            printf("%s = ", name);
            hex(base, o->stride);
            printf("\n");
            continue;
        }
        for (j = 0; j < o->cls->n; j++) {
            const CsField *f = &o->cls->f[j];

            if (f->kind == 'R') {
                printf("%s.%s = ", name, f->name);
                hex(base + f->off, f->size);
                printf("\n");
            } else if (f->kind == 'P') {
                void *v;

                memcpy(&v, base + f->off, sizeof v);
                printf("%s.%s -> %s\n", name, f->name, label(v));
            } else {
                uint32_t v;

                memcpy(&v, base + f->off, 4);
                printf("%s.%s = vt:%s\n", name, f->name, vt_name(v));
            }
        }
    }
}

static uint32_t fnv(const uint8_t *p, size_t n)
{
    uint32_t h = 0x811c9dc5u;
    size_t i;

    for (i = 0; i < n; i++)
        h = (h ^ p[i]) * 0x01000193u;
    return h;
}

static void sdump(void)
{
    int i, n, k;
    uint32_t tiv;

    memcpy(&tiv, &snap.TotalInterestingValue, 4);

    printf("snap name=%s t=%d et=%d blt=%d elt=%d flags=%d,%d,%d,%d "
           "depth=%d ovf=%d secnum=%u pd=%d tiv=%08x pos=%d size=%d "
           "breaks=%d\n", snap.Name, (int)snap.Time, (int)snap.EndTime,
           (int)snap.BeginLoopTime, (int)snap.EndLoopTime,
           snap.TakingSnapshotFlag, snap.RestoringSnapshotFlag,
           snap.TakingChecksumFlag, snap.VerifyingChecksumFlag,
           snap.CurrentSectionDepth, snap.OverflowedFlag,
           (unsigned)snap.CurrentSectionNumber, (int)snap.PrintDepth,
           (unsigned)tiv, (int)snap.DataPosition,
           (int)snap.SizeofData, (int)replay_breaks);
    for (i = 0; i < REPLAY_SNAPSHOT_SECTIONS; i++) {
        const ReplaySectionInfo *si = &snap.SectionInfo[i];

        if (!si->Name && !si->Object && !si->Number && !si->NumMoveData
            && !si->ChecksumErrorDetected && !si->Size)
            continue;
        printf("sec %d name=%s obj=%s num=%u nmd=%u err=%d size=%d\n", i,
               si->Name ? cstr(p32_ptr(si->Name)) : "-",
               label(si->Object ? p32_ptr(si->Object) : NULL),
               (unsigned)si->Number, (unsigned)si->NumMoveData,
               (int)si->ChecksumErrorDetected, (int)si->Size);
    }
    n = snap.DataPosition > snap.SizeofData ? snap.DataPosition
                                            : snap.SizeofData;
    if (n < 0)
        n = 0;
    if (n > 4096)
        n = 4096;
    printf("data fnv=%08x\n", (unsigned)fnv(snap.Data, sizeof snap.Data));
    for (k = 0; k < n; k += 64) {
        printf("d %d ", k);
        hex(snap.Data + k, (size_t)((n - k) < 64 ? n - k : 64));
        printf("\n");
    }
}

// The pointer a field holds, or a holder block's first word with "-".
static void **ptr_at(const char *r, const char *path)
{
    Obj *ob;
    uint8_t *at = ref(r, &ob);

    if (!strcmp(path, "-"))
        return (void **)at;
    {
        const CsField *f = find_field(ob->cls, path);

        if (f->kind != 'P')
            die("not a pointer:", path);
        return (void **)(at + f->off);
    }
}

// ------------------------------------------------------------------ calls

typedef void (*SnapFn)(void *self, ReplaySnapshot *s);

static void call(const char *fn, void *p, int n)
{
    ReplaySnapshot *s = &snap;

    if (!strcmp(fn, "average"))
        average_do_snapshot(p, s);
    else if (!strcmp(fn, "piderror"))
        pid_error_do_snapshot(p, s);
    else if (!strcmp(fn, "drivetarget"))
        drivetarget_do_snapshot(p, s);
    else if (!strcmp(fn, "cardriver"))
        cardriver_do_snapshot(p, s);
    else if (!strcmp(fn, "psychodriver"))
        psychodriver_do_snapshot(p, s);
    else if (!strcmp(fn, "realdriver"))
        realdriver_do_snapshot(p, s);
    else if (!strcmp(fn, "drivinglocation"))
        drivinglocation_do_snapshot(p, s);
    else if (!strcmp(fn, "drivingchoice"))
        drivingchoice_do_snapshot(p, s);
    else if (!strcmp(fn, "nrpi"))
        nrpi_do_snapshot(p, s);
    else if (!strcmp(fn, "nearbycarlist"))
        nearbycarlist_do_snapshot(p, s);
    else if (!strcmp(fn, "drivinginfo"))
        drivinginformation_do_snapshot(p, s);
    else if (!strcmp(fn, "aiplan"))
        aiplan_do_snapshot(p, s);
    else if (!strcmp(fn, "aiaction"))
        aiaction_do_snapshot(p, s);
    else if (!strcmp(fn, "actionptr"))
        aiaction_do_pointer_snapshot(p, s);
    else if (!strcmp(fn, "avoidcars"))
        aiavoidcars_do_snapshot(p, s);
    else if (!strcmp(fn, "justdrive"))
        aijustdrive_do_snapshot(p, s);
    else if (!strcmp(fn, "draft"))
        aidraft_do_snapshot(p, s);
    else if (!strcmp(fn, "pass"))
        aipass_do_snapshot(p, s);
    else if (!strcmp(fn, "nudgecar"))
        ainudgecar_do_snapshot(p, s);
    else if (!strcmp(fn, "block"))
        aiblock_do_snapshot(p, s);
    else if (!strcmp(fn, "pullover"))
        aipullover_do_snapshot(p, s);
    else if (!strcmp(fn, "getunstuck"))
        aigetunstuck_do_snapshot(p, s);
    else if (!strcmp(fn, "avoidroadblock"))
        aiavoidroadblock_do_snapshot(p, s);
    else if (!strcmp(fn, "ijustgothit"))
        aijustgothit_do_snapshot(p, s);
    else if (!strcmp(fn, "accidentrecovery"))
        aiaccidentrecovery_do_snapshot(p, s);
    else if (!strcmp(fn, "aicarcontroller"))
        aicarcontroller_do_snapshot(p, s);
    else if (!strcmp(fn, "aidriver"))
        aidriver_do_snapshot(p, s);
    else if (!strcmp(fn, "trafficdriver"))
        trafficdriver_do_snapshot(p, s);
    else if (!strcmp(fn, "tracked"))
        trackedcontroller_do_snapshot(p, s);
    else if (!strcmp(fn, "realcontroller"))
        realcontroller_do_snapshot(p, s);
    else if (!strcmp(fn, "copdriver"))
        copdriver_do_snapshot(p, s);
    else if (!strcmp(fn, "copmover"))
        copmover_do_snapshot(p, s);
    else if (!strcmp(fn, "beltmover"))
        beltmover_do_snapshot(p, s);
    else if (!strcmp(fn, "mellowmover"))
        mellowmover_do_snapshot(p, s);
    else if (!strcmp(fn, "mellovator"))
        mellovator_do_snapshot(p, s);
    else if (!strcmp(fn, "spline"))
        spline_do_snapshot(p, s);
    else if (!strcmp(fn, "quickspline"))
        quickspline_do_snapshot(p, s, n);
    else if (!strcmp(fn, "carcontroller"))
        carcontroller_do_snapshot(p, s);
    else
        die("no function", fn);
}

// ------------------------------------------------------------------ ops

static int unhex(const char *h, uint8_t *out, size_t cap)
{
    size_t n = strlen(h) / 2, i;

    if (n > cap)
        die("hex too long:", h);
    for (i = 0; i < n; i++) {
        unsigned v;

        sscanf(h + 2 * i, "%2x", &v);
        out[i] = (uint8_t)v;
    }
    return (int)n;
}

// A link's target: `0`, or an object with `-`, a field path or `+N`.
static void *target(char **a)
{
    Obj *ob2;
    uint8_t *at2;

    if (!strcmp(a[0], "0"))
        return NULL;
    at2 = ref(a[0], &ob2);
    if (!strcmp(a[1], "-"))
        return at2;
    if (a[1][0] == '+')
        return at2 + atoi(a[1] + 1);
    return at2 + path_off(ob2->cls, a[1]);
}

static World world;

static void op(char **a, int n)
{
    const char *o = a[0];
    Obj *ob;
    uint8_t *at, buf[1024];

    if (!strcmp(o, "new")) {
        const CsClass *c = find_class(a[2]);
        int cnt = n > 3 ? atoi(a[3]) : 1;

        add(a[1], calloc((size_t)cnt, c->size), c, cnt, c->size);
    } else if (!strcmp(o, "newb")) {
        size_t sz = (size_t)atoi(a[2]);

        add(a[1], calloc(1, sz), NULL, 1, sz);
    } else if (!strcmp(o, "set")) {
        const CsField *f;
        int k;

        at = ref(a[1], &ob);
        f = find_field(ob->cls, a[2]);
        k = unhex(a[3], buf, sizeof buf);
        if (f->kind != 'R' || (size_t)k != f->size)
            die("set: size or kind of", a[2]);
        memcpy(at + f->off, buf, f->size);
    } else if (!strcmp(o, "setb")) {
        int k;

        at = ref(a[1], &ob);
        k = unhex(a[3], buf, sizeof buf);
        memcpy(at + atoi(a[2]), buf, (size_t)k);
    } else if (!strcmp(o, "drvvt")) {
        uint32_t v = vt_image(a[2]);

        at = ref(a[1], &ob);
        memcpy(at + offsetof(CarDriver, _vtable), &v, 4);
    } else if (!strcmp(o, "link")) {
        void *v = target(a + 3);

        memcpy(ptr_at(a[1], a[2]), &v, sizeof v);
    } else if (!strcmp(o, "vt")) {
        const CsField *f;
        uint32_t v = vt_image(a[3]);

        at = ref(a[1], &ob);
        f = find_field(ob->cls, a[2]);
        if (f->kind != 'V')
            die("vt: not a vptr:", a[2]);
        memcpy(at + f->off, &v, 4);
    } else if (!strcmp(o, "world")) {
        // world|car,car,...|- : the cars of pCurrentWorld, in order.
        char *p = a[1];

        memset(&world, 0, sizeof world);
        while (p && *p && strcmp(p, "-")) {
            char *c = strchr(p, ',');

            if (c)
                *c++ = 0;
            world.CarTable[world.TotalNumCars++] = (Car *)ref(p, &ob);
            p = c;
        }
        pCurrentWorld = &world;
    } else if (!strcmp(o, "route")) {
        // route|id|number|points: a TrackRoute, its points numbered for it,
        // in the manager's table.
        TrackRoute *r = calloc(1, sizeof *r);
        int num = atoi(a[2]), pts = atoi(a[3]), i;
        char id[32];

        r->RouteNumber = (int16_t)num;
        for (i = 0; i < pts; i++)
            r->TrackRoutePointTable[i].RouteNumber = (uint8_t)num;
        TheTrackRouteManager.pTrackRoutes[num] = r;
        // The points first, so a pointer into one reads as `idp[i]`.
        snprintf(id, sizeof id, "%sp", a[1]);
        add(id, r->TrackRoutePointTable, NULL, TRACK_ROUTE_MAX_POINTS,
            sizeof r->TrackRoutePointTable[0]);
        add(a[1], r, NULL, 1, sizeof *r);
    } else if (!strcmp(o, "copmgr")) {
        // copmgr|id|n: pCopManager, its roadblocks registered as `id`.
        pCopManager = calloc(1, sizeof *pCopManager);
        add(a[1], pCopManager->RoadBlocks, NULL, atoi(a[2]),
            sizeof(tRoadBlock));
    } else if (!strcmp(o, "player")) {
        // player|id|slot|number
        struct Player *p = calloc(1, sizeof *p);

        p->PlayerNumber = atoi(a[3]);
        PlayerPlayersByNumber[atoi(a[2])] = p;
        add(a[1], p, NULL, 1, sizeof *p);
    } else if (!strcmp(o, "timer")) {
        WorldTimer = atoi(a[1]);
        WorldLoopCounter = atoi(a[2]);
    } else if (!strcmp(o, "sinit")) {
        static char names[64][32];
        static int nn;
        char *nm = names[nn++ & 63];

        snprintf(nm, 32, "%s", a[1]);
        ReplaySnapshot_Init(&snap, nm);
    } else if (!strcmp(o, "sflags")) {
        snap.TakingSnapshotFlag = (int8_t)atoi(a[1]);
        snap.RestoringSnapshotFlag = (int8_t)atoi(a[2]);
        snap.TakingChecksumFlag = (int8_t)atoi(a[3]);
        snap.VerifyingChecksumFlag = (int8_t)atoi(a[4]);
    } else if (!strcmp(o, "srewind")) {
        snap.SizeofData = snap.DataPosition;
        snap.DataPosition = 0;
    } else if (!strcmp(o, "sdump")) {
        sdump();
    } else if (!strcmp(o, "call")) {
        call(a[1], ref(a[2], &ob), n > 3 ? atoi(a[3]) : 0);
    } else if (!strcmp(o, "dump")) {
        dump_obj(find_obj(a[1]));
    } else if (!strcmp(o, "dumpp")) {
        printf("%s %s -> %s\n", a[1], a[2], label(*ptr_at(a[1], a[2])));
    } else if (!strcmp(o, "dumpa")) {
        // dumpa|ref|field|Class: the action the pointer holds, given the
        // class if it is a pool slot not yet dumped.
        void *v = *ptr_at(a[1], a[2]);
        int i;

        printf("%s %s -> %s\n", a[1], a[2], label(v));
        for (i = 0; v && i < nobjs; i++) {
            if (objs[i].base != v)
                continue;
            if (objs[i].cls == NULL)
                objs[i].cls = find_class(a[3]);
            dump_obj(&objs[i]);
            break;
        }
    } else {
        die("no op", o);
    }
}

int main(int argc, char **argv)
{
    static char line[8192];
    FILE *f;

    if (argc != 2)
        die("usage:", "aisnap_test script.txt");
    f = fopen(argv[1], "rb");
    if (f == NULL)
        die("cannot open", argv[1]);
    // A crash keeps everything printed before it.
    setvbuf(stdout, NULL, _IOLBF, 0);

    cardriver_install_vtables();
    psychodriver_install_vtables();
    realdriver_install_vtable();
    aiaction_install_vtables();
    aiactions_install_vtables();
    vt_install(REC_IMAGE, rec_vt, 32);

    while (fgets(line, sizeof line, f)) {
        char *a[16];
        int n = 0;
        char *p = line;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        if (line[0] == '#') {
            printf("%s\n", line);
            continue;
        }
        printf("> %s\n", line);
        while (p && n < 16) {
            a[n++] = p;
            p = strchr(p, '|');
            if (p)
                *p++ = 0;
        }
        op(a, n);
    }
    fclose(f);
    return 0;
}
