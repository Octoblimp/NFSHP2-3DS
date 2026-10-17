// copmgrsnap_test -- the harness of tools/copmgrsnap_check.py (TASKS 72e-3):
// tCopManager::DoSnapshot, copmgrsnap.c, over a script.
//
// The same shape as copsnap_test.c, which it copies the ops of:
// tools/copmgrsnap_check.py writes each record's field table in at the
// marker below -- name, host offset, host size, kind -- from the port's
// headers, so a script line names a field and each side writes and dumps it
// at its own offset. A pointer prints as the object and field it points
// into. The model (retail's code in mipsemu) reads the same script and must
// print the same lines.
//
// Recorded here, as the model's stubs print them: the pursuits' and the
// strips' snapshots; the cops' (slot 32 of tPlayerCop's and tAICop's
// tables, which this installs at the image's addresses); the strip's
// destructor (slot 8 of tSpikeStrip's); DeletePursuit, which unlinks the
// pursuit; NewPursuit, which makes one `P<n>` with the id at the list's
// tail; bOMalloc, which makes a strip `S<n>`; and the strip's default
// constructor, which sets its table. What the linked files reach outside
// that comes from copmgrsnap_stubs.c and copmgrsnap_stubdata.c, which
// `copmgrsnap_check.py --stubs` writes; each of those functions stops the
// run.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bslotpool.h"
#include "cop.h"
#include "copmanager.h"
#include "copmgr.h"
#include "p32.h"
#include "pursuit.h"
#include "race.h"
#include "replay.h"
#include "spikestrip.h"
#include "vtable.h"
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

// @FIELDS@

#ifndef CS_GENERATED
#error "built from tools/copmgrsnap_check.py, which writes the field tables in"
#endif

#define MAX_OBJS    1024
#define MAX_WALK    16

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
    fprintf(stderr, "copmgrsnap_test: %s %s\n", what, arg);
    exit(2);
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

void tpursuit_do_snapshot(tPursuit *p, ReplaySnapshot *s)
{
    SNAPREC("pursuit", p, s);
}

void tspikestrip_do_snapshot(tSpikeStrip *t, ReplaySnapshot *s)
{
    SNAPREC("strip", t, s);
}

static void rec_playercop(void *c, ReplaySnapshot *s)
{
    SNAPREC("playercopsnap", c, s);
}

static void rec_aicop(void *c, ReplaySnapshot *s)
{
    SNAPREC("aicopsnap", c, s);
}

static void rec_strip_dtor(void *t, int32_t flags)
{
    printf("stripdtor %s flags=%d %s\n", label(t), (int)flags, where());
}

static void rec_unexpected(void)
{
    printf("UNEXPECTED slot\n");
    fflush(stdout);
    exit(3);
}

static const VtEntry cop_rec_vt[2][5] = {
    { {0, 0, NULL}, {0, 0, rec_unexpected}, {0, 0, rec_unexpected},
      {0, 0, rec_unexpected}, {0, 0, (VtFn)rec_playercop} },
    { {0, 0, NULL}, {0, 0, rec_unexpected}, {0, 0, rec_unexpected},
      {0, 0, rec_unexpected}, {0, 0, (VtFn)rec_aicop} },
};

static const VtEntry strip_rec_vt[] = {
    {0, 0, NULL}, {0, 0, (VtFn)rec_strip_dtor},
};

// DeletePursuit: unlinks the pursuit, nothing more.
void copmanager_delete_pursuit(tCopManager *m, tPursuit *p)
{
    tPursuitNode *nx = p->Node.Next, *pv = p->Node.Prev;

    printf("delpursuit m=%s p=%s %s\n", label(m), label(p), where());
    pv->Next = nx;
    nx->Prev = pv;
}

static int npursuits_made, nstrips_made;

// NewPursuit: `P<n>`, its id set, at the tail of the list.
tPursuit *copmanager_new_pursuit(tCopManager *m, int32_t id, struct Car *car)
{
    tPursuit *p = calloc(1, sizeof *p);
    char      name[24];

    snprintf(name, sizeof name, "P%d", npursuits_made++);
    add(name, p, find_class("tPursuit"), 1, sizeof *p);
    p->nPursuitId = (int8_t)id;
    p->Node.Next = &m->PursuitList;
    p->Node.Prev = m->PursuitList.Prev;
    m->PursuitList.Prev->Next = &p->Node;
    m->PursuitList.Prev = &p->Node;
    printf("newpursuit m=%s id=%d car=%s -> %s %s\n", label(m), (int)id,
           label(car), name, where());
    return p;
}

// bOMalloc: a strip `S<n>`, zeroed.
void *bSlotOMalloc(BSlotPool *pool)
{
    tSpikeStrip *t = calloc(1, sizeof *t);
    char         name[24];

    snprintf(name, sizeof name, "S%d", nstrips_made++);
    add(name, t, find_class("tSpikeStrip"), 1, sizeof *t);
    printf("omalloc pool=%s -> %s %s\n", label(pool), name, where());
    return t;
}

// The default constructor: its table, as retail's sets it.
tSpikeStrip *tspikestrip_construct_default(tSpikeStrip *s)
{
    printf("stripctor %s %s\n", label(s), where());
    s->vptr = TSPIKESTRIP_VTABLE;
    return s;
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
                printf("%s.%s = vt:%08x\n", name, f->name, (unsigned)v);
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

// One list of the manager, forwards with each pursuit's id, then back.
static void walk(const char *what, tPursuitNode *head, int ids)
{
    tPursuitNode *n;
    int k;

    printf("%s f:", what);
    for (n = head->Next, k = 0; n != head && k < MAX_WALK; n = n->Next, k++) {
        if (ids)
            printf(" %s/%d", label(n), (int)((tPursuit *)(void *)n)->nPursuitId);
        else
            printf(" %s", label(n));
    }
    printf("%s\n", n != head ? " ..." : "");
    printf("%s b:", what);
    for (n = head->Prev, k = 0; n != head && k < MAX_WALK; n = n->Prev, k++)
        printf(" %s", label(n));
    printf("%s\n", n != head ? " ..." : "");
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
    } else if (!strcmp(o, "link")) {
        const CsField *f;
        void *v = target(a + 3);

        at = ref(a[1], &ob);
        f = find_field(ob->cls, a[2]);
        if (f->kind != 'P')
            die("not a pointer:", a[2]);
        memcpy(at + f->off, &v, sizeof v);
    } else if (!strcmp(o, "spool")) {
        SpikeStripSlotPool = (BSlotPool *)(void *)ref(a[1], &ob);
    } else if (!strcmp(o, "world")) {
        // world|n: pCurrentWorld, made once, with CopCarPos n.
        static World *w;

        if (w == NULL) {
            w = calloc(1, sizeof *w);
            add("wld", w, NULL, 1, sizeof *w);
        }
        w->CopCarPos = atoi(a[1]);
        pCurrentWorld = w;
    } else if (!strcmp(o, "beacop")) {
        TheRaceParameters.BeACop = atoi(a[1]);
    } else if (!strcmp(o, "lists")) {
        tCopManager *m = (tCopManager *)(void *)ref(a[1], &ob);

        walk("plist", &m->PursuitList, 1);
        walk("slist", &m->SpikeStripList, 0);
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
        at = ref(a[2], &ob);
        if (strcmp(a[1], "copmanager"))
            die("no function", a[1]);
        copmanager_do_snapshot((tCopManager *)(void *)at, &snap);
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
        die("usage:", "copmgrsnap_test script.txt");
    f = fopen(argv[1], "rb");
    if (f == NULL)
        die("cannot open", argv[1]);
    // A crash keeps everything printed before it.
    setvbuf(stdout, NULL, _IOLBF, 0);

    // The recording tables, at the image's addresses.
    vt_install(TPLAYERCOP_VTABLE, cop_rec_vt[0], 5);
    vt_install(TAICOP_VTABLE, cop_rec_vt[1], 5);
    vt_install(TSPIKESTRIP_VTABLE, strip_rec_vt, 2);

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
