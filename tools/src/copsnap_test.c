// copsnap_test -- the harness of tools/copsnap_check.py (TASKS 72e): the
// cops' part of a replay snapshot -- DroppedSpikes', Rocket's, tSpikeStrip's
// and the chopper's DoSnapshots (72e-1); tPursuit's, tPlayerCop's and
// tAICop's with all they call in copsnap.c (72e-2) -- over a script.
//
// The same shape as worldsnap_test.c, which it copies the ops of:
// tools/copsnap_check.py writes each record's field table in at the marker
// below -- name, host offset, host size, kind -- from the port's headers, so
// a script line names a field and each side writes and dumps it at its own
// offset. A pointer prints as the object and field it points into. The
// model (retail's code in mipsemu) reads the same script and must print the
// same lines.
//
// Recorded here, as the model's stubs print them: Smokeable's snapshot,
// World's car pointer and its plain pointer, the route manager's route and
// point pointers, TrackPathCoordinate's snapshot, the strip's Init, the
// chopper's RemoveChopperFromWorld and ClearVariables, the cop manager's
// roadblock pointer, the pursuit's IsCopInPursuit (which returns what an
// `incop` op set) and DriveTarget's snapshot. What the linked files reach
// outside that comes from copsnap_stubs.c and copsnap_stubdata.c, which
// `copsnap_check.py --stubs` writes; each of those functions stops the run.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "barricade.h"
#include "car.h"
#include "chopper.h"
#include "collisionbody.h"
#include "cop.h"
#include "copmanager.h"
#include "drivetarget.h"
#include "munition.h"
#include "p32.h"
#include "pursuit.h"
#include "replay.h"
#include "smokeable.h"
#include "spikestrip.h"
#include "trackpath.h"
#include "trackroute.h"
#include "world.h"

typedef struct Chopper Chopper;

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

// @FIELDS@

#ifndef CS_GENERATED
#error "built from tools/copsnap_check.py, which writes the field tables in"
#endif

#define MAX_OBJS    1024
#define MAX_LIST    16

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

static void die(const char *what, const char *arg)
{
    fprintf(stderr, "copsnap_test: %s %s\n", what, arg);
    exit(2);
}

// The recording table's image address: no class the port has uses it.
#define REC_IMAGE 0x7e000000u

static const struct { const char *name; uint32_t image; } vts[] = {
    {"rec", REC_IMAGE},
};

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

// `0` or an object.
static void *addr(const char *r)
{
    Obj *ob;

    return strcmp(r, "0") ? (void *)ref(r, &ob) : NULL;
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
            snprintf(name, sizeof name, "%.23s[%zu]", o->id, el);
        else
            snprintf(name, sizeof name, "%.23s", o->id);
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

// The live section, its depth and name, and where the data stands: a move
// swapped with a recorded call shows only there.
static const char *where(void)
{
    static char buf[96];
    int d = snap.CurrentSectionDepth;

    if (d < 0) {
        snprintf(buf, sizeof buf, "depth=%d top=- at=%d", d,
                 (int)snap.DataPosition);
    } else {
        uint32_t h = snap.SectionInfo[d].Name;

        snprintf(buf, sizeof buf, "depth=%d top=%s at=%d", d,
                 h ? (const char *)p32_ptr(h) : "-", (int)snap.DataPosition);
    }
    return buf;
}

static const char *snaparg(const void *s)
{
    return s == (const void *)&snap ? "snap" : "?";
}

static uint32_t fnv(const uint8_t *p, size_t n)
{
    uint32_t h = 0x811c9dc5u;
    size_t i;

    for (i = 0; i < n; i++)
        h = (h ^ p[i]) * 0x01000193u;
    return h;
}

// ----------------------------------------------------------------- stubs
//
// What the model stubs in retail, here as lines both print.

#define SNAPREC(what, obj, s) \
    printf("%s %s s=%s %s\n", what, label(obj), snaparg(s), where())

void smokeable_do_snapshot(CollisionBody *b, ReplaySnapshot *s)
{
    SNAPREC("smokeable", b, s);
}

void trackpath_coord_do_snapshot(TrackPathCoordinate *c, ReplaySnapshot *s)
{
    SNAPREC("tpcoord", c, s);
}

void world_do_car_pointer_snapshot(const World *w, struct Car **pp,
                                   ReplaySnapshot *s)
{
    printf("carptr w=%s pp=%s s=%s %s\n", label(w), label(pp), snaparg(s),
           where());
}

void trmgr_do_route_pointer_snapshot(TrackRouteManager *m, ReplaySnapshot *s,
                                     TrackRoute **pp)
{
    printf("routeptr m=%s s=%s pp=%s %s\n", label(m), snaparg(s), label(pp),
           where());
}

void trmgr_do_point_pointer_snapshot_in_route(TrackRouteManager *m,
                                              ReplaySnapshot *s,
                                              TrackRoutePoint **pp,
                                              TrackRoute *route)
{
    printf("pointptr m=%s s=%s pp=%s route=%s %s\n", label(m), snaparg(s),
           label(pp), label(route), where());
}

void tspikestrip_init(tSpikeStrip *t, const bVector2 *a, const bVector2 *b,
                      int32_t id, float lifetime)
{
    uint32_t bits;

    memcpy(&bits, &lifetime, 4);
    printf("stripinit %s a=%s b=%s id=%d life=%08x %s\n", label(t), label(a),
           label(b), (int)id, (unsigned)bits, where());
}

void chopper_remove_from_world(struct Chopper *h)
{
    printf("removechopper %s %s\n", label(h), where());
}

void chopper_clear_variables(struct Chopper *h)
{
    printf("clearvariables %s %s\n", label(h), where());
}

void world_do_pointer_snapshot(const World *w, ReplaySnapshot *s,
                               struct Car **pp)
{
    printf("worldptr w=%s s=%s pp=%s %s\n", label(w), snaparg(s), label(pp),
           where());
}

void copmanager_do_road_block_pointer_snapshot(tCopManager *m,
                                               ReplaySnapshot *s,
                                               tRoadBlock **pp)
{
    printf("rbptr m=%s s=%s pp=%s %s\n", label(m), snaparg(s), label(pp),
           where());
}

static int32_t incop_ret;

int32_t tpursuit_is_cop_in_pursuit(const tPursuit *p, const tCop *c)
{
    printf("incop p=%s c=%s -> %d %s\n", label(p), label(c), (int)incop_ret,
           where());
    return incop_ret;
}

void drivetarget_do_snapshot(DriveTarget *t, ReplaySnapshot *s)
{
    SNAPREC("drivetarget", t, s);
}

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
            snprintf(name, sizeof name, "%.23s[%d]", o->id, i);
        else
            snprintf(name, sizeof name, "%.23s", o->id);
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

static void call(const char *fn, void *p)
{
    ReplaySnapshot *s = &snap;

    if (!strcmp(fn, "spikes"))
        droppedspikes_do_snapshot(p, s);
    else if (!strcmp(fn, "rocket"))
        rocket_do_snapshot(p, s);
    else if (!strcmp(fn, "strip"))
        tspikestrip_do_snapshot(p, s);
    else if (!strcmp(fn, "chopper"))
        chopper_do_snapshot(p, s);
    else if (!strcmp(fn, "pursuit"))
        tpursuit_do_snapshot(p, s);
    else if (!strcmp(fn, "playercop"))
        tplayercop_do_snapshot(p, s);
    else if (!strcmp(fn, "aicop"))
        taicop_do_snapshot(p, s);
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
    } else if (!strcmp(o, "curworld")) {
        pCurrentWorld = addr(a[1]);
    } else if (!strcmp(o, "copmgr")) {
        // copmgr|id: pCopManager, its first four radar traps as `idt`
        // first, so a pointer into one reads as `idt[i]`.
        char id[32];

        pCopManager = calloc(1, sizeof *pCopManager);
        snprintf(id, sizeof id, "%st", a[1]);
        add(id, pCopManager->SpeedTraps, find_class("tSpeedTrap"), 4,
            sizeof(tSpeedTrap));
        add(a[1], pCopManager, NULL, 1, sizeof *pCopManager);
    } else if (!strcmp(o, "mcop")) {
        pCopManager->Cops[atoi(a[1])] = addr(a[2]);
    } else if (!strcmp(o, "mpur")) {
        pCopManager->PursuitsById[atoi(a[1])] = addr(a[2]);
    } else if (!strcmp(o, "newcar")) {
        // newcar|id|player: a car whose pPlayer is `player`.
        struct Car *c = calloc(1, sizeof *c);

        c->pPlayer = addr(a[2]);
        add(a[1], c, NULL, 1, sizeof *c);
    } else if (!strcmp(o, "newworld")) {
        // newworld|id|heli: a world whose Helicopter is `heli`.
        World *w = calloc(1, sizeof *w);

        w->Helicopter = addr(a[2]);
        add(a[1], w, NULL, 1, sizeof *w);
    } else if (!strcmp(o, "incop")) {
        incop_ret = atoi(a[1]);
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
        call(a[1], ref(a[2], &ob));
    } else if (!strcmp(o, "dump")) {
        dump_obj(find_obj(a[1]));
    } else {
        die("no op", o);
    }
}

int main(int argc, char **argv)
{
    static char line[16384];
    FILE *f;

    if (argc != 2)
        die("usage:", "copsnap_test script.txt");
    f = fopen(argv[1], "rb");
    if (f == NULL)
        die("cannot open", argv[1]);
    // A crash keeps everything printed before it.
    setvbuf(stdout, NULL, _IOLBF, 0);

    // The globals, as the model registers them.
    add("trm", &TheTrackRouteManager, NULL, 1, 4);

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
