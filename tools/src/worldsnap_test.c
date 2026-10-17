// worldsnap_test -- the harness of tools/worldsnap_check.py (TASKS 72d-2):
// World's and RaceCoordinator's DoSnapshots, the cops', the smokeables' and
// the collision bodies' SnapshotEverythings, over a script.
//
// The same shape as racesnap_test.c, which it copies the ops of:
// tools/worldsnap_check.py writes each record's field table in at the
// marker below -- name, host offset, host size, kind -- from the port's
// headers, so a script line names a field and each side writes and dumps
// it at its own offset. A pointer prints as the object and field it points
// into. The model (retail's code in mipsemu) reads the same script and must
// print the same lines.
//
// Recorded here, as the model's stubs print them: every snapshot another
// task checks, the restore's flushes and resets, the pools, the
// constructors, CreateSmokeable, the lookups, GetNameHash, and the bodies'
// tables through a recording table whose GetSmokeType answers a value.
// What the linked files reach outside that comes from worldsnap_stubs.c
// and worldsnap_stubdata.c, which `worldsnap_check.py --stubs` writes; each
// of those functions stops the run.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "acidsys.h"
#include "bslotpool.h"
#include "car.h"
#include "collisionbody.h"
#include "copmanager.h"
#include "p32.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "racecore.h"
#include "realtime.h"
#include "replay.h"
#include "rigidbody.h"
#include "shake.h"
#include "smokeable.h"
#include "sundraw.h"
#include "topology.h"
#include "trackgraph.h"
#include "traffictele.h"
#include "vtable.h"
#include "world.h"
#include "worldobject.h"

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
#error "built from tools/worldsnap_check.py, which writes the field tables in"
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
    fprintf(stderr, "worldsnap_test: %s %s\n", what, arg);
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

static uint32_t fnv_str(const char *s)
{
    return fnv((const uint8_t *)s, strlen(s));
}

// --------------------------------------------------------------- recorders

static void rec_log(int slot, void *self, void *a1)
{
    printf("rec vt%d this=%s", slot, label(self));
    if (slot == 16 || slot == 24)
        printf(" s=%s", snaparg(a1));
    printf(" %s\n", where());
}

#define REC(n) \
    static void rec_##n(void *self, void *a1) { rec_log(8 * (n), self, a1); }
REC(1)  REC(2)  REC(3)  REC(4)  REC(5)  REC(6)  REC(7)  REC(8)
REC(9)  REC(10) REC(11) REC(12) REC(13) REC(14) REC(15) REC(16)
REC(17) REC(18) REC(19) REC(20) REC(21) REC(22) REC(23) REC(24)
REC(25) REC(27) REC(28) REC(29) REC(30) REC(31)
#undef REC

// GetSmokeType, slot 208: the object's label hashed, as the model answers.
static int32_t rec_26(void *self)
{
    const char *l = label(self);

    printf("rec vt208 this=%s %s\n", l, where());
    return (int32_t)fnv_str(l);
}

#define E(n) { 0, 0, (VtFn)rec_##n }
static const VtEntry rec_vt[32] = {
    { 0, 0, NULL }, E(1), E(2), E(3), E(4), E(5), E(6), E(7), E(8), E(9),
    E(10), E(11), E(12), E(13), E(14), E(15), E(16), E(17), E(18), E(19),
    E(20), E(21), E(22), E(23), E(24), E(25), E(26), E(27), E(28), E(29),
    E(30), E(31),
};
#undef E

// ----------------------------------------------------------------- stubs
//
// What the model stubs in retail, here as lines both print.

#define SNAPREC(what, obj, s) \
    printf("%s %s s=%s %s\n", what, label(obj), snaparg(s), where())

void WorldTimeDoSnapshot(ReplaySnapshot *s)
{
    printf("worldtime s=%s %s\n", snaparg(s), where());
}

void traffic_teleporter_do_snapshot(TrafficTeleporter *t, ReplaySnapshot *s)
{
    SNAPREC("teleporter", t, s);
}

void trackgraph_do_snapshot(tTrackGraph *g, ReplaySnapshot *s)
{
    SNAPREC("trackgraph", g, s);
}

void car_do_snapshot(Car *c, ReplaySnapshot *s)
{
    SNAPREC("car", c, s);
}

void race_do_snapshot(Race *r, ReplaySnapshot *s)
{
    SNAPREC("race", r, s);
}

void player_do_snapshot(struct Player *p, ReplaySnapshot *s)
{
    SNAPREC("player", p, s);
}

void staticcollisionbody_do_snapshot(CollisionBody *b, ReplaySnapshot *s)
{
    SNAPREC("staticbody", b, s);
}

void dynamiccollisionbody_do_snapshot(CollisionBody *b, ReplaySnapshot *s)
{
    SNAPREC("dynamicbody", b, s);
}

void rigidbody_do_snapshot(RigidBody *rb, ReplaySnapshot *s)
{
    SNAPREC("rigidbody", rb, s);
}

void cbwitness_do_snapshot(CollisionBodyWitness *w, ReplaySnapshot *s)
{
    SNAPREC("cbwitness", w, s);
}

static void h_copmanager(struct tCopManager *m, ReplaySnapshot *s)
{
    SNAPREC("copmanager", m, s);
}

static void h_chopper(struct Chopper *h, ReplaySnapshot *s)
{
    SNAPREC("chopper", h, s);
}

static void h_flushclans(void)
{
    printf("flushclans %s\n", where());
}

static void h_flushferns(void)
{
    printf("flushferns %s\n", where());
}

void cbwitness_eliminate_all(void)
{
    printf("eliminatewitnesses %s\n", where());
}

void delete_smokeable_collision_bodies(void)
{
    printf("deletesmokeables %s\n", where());
}

void acid_system_kill_all_active_effects(AcidEffectSystem *s)
{
    printf("killeffects %s %s\n", label(s), where());
}

void reset_camera_shakers(void)
{
    printf("resetshakers glare=%d %s\n", (int)bResetGlare, where());
}

void dynamiccollisionbody_update_position(DynamicCollisionBody *d)
{
    printf("updateposition %s %s\n", label(d), where());
}

SmokeableSpawner *smokeable_get_spawner(int32_t i)
{
    printf("getspawner %d %s\n", (int)i, where());
    return i < 0 || pSmokeableSpawners == NULL ? NULL
                                               : &pSmokeableSpawners[i];
}

int32_t smokeable_get_spawner_index(const SmokeableSpawner *sp)
{
    printf("spawnerindex %s %s\n", label(sp), where());
    return sp == NULL ? -1 : (int32_t)(sp - pSmokeableSpawners);
}

// The smokeable whose model it is, hashed.
uint32_t worldobject_get_name_hash(WorldObject *o)
{
    const char *l =
        label((uint8_t *)o - offsetof(Smokeable, TheWorldObject));

    printf("namehash %s %s\n", l, where());
    return fnv_str(l);
}

// What each pool's allocation makes, as the model names them.
static int made[4];

static void *make(char prefix, const char *cls)
{
    static const char prefixes[] = "VTWS";
    const CsClass *c = find_class(cls);
    int k = (int)(strchr(prefixes, prefix) - prefixes);
    char id[24];
    void *p = calloc(1, c->size);

    snprintf(id, sizeof id, "%c%d", prefix, made[k]++);
    add(id, p, c, 1, c->size);
    return p;
}

void *bSlotOMalloc(BSlotPool *pool)
{
    const char *l = label(pool);

    printf("omalloc %s %s\n", l, where());
    if (!strcmp(l, "vpool"))
        return make('V', "VirginSmokeable");
    if (!strcmp(l, "tppool"))
        return make('T', "TrackPolygonCollisionBody");
    if (!strcmp(l, "witpool"))
        return make('W', "CollisionBodyWitness");
    die("no pool", l);
    return NULL;
}

VirginSmokeable *virginsmokeable_init(VirginSmokeable *v,
                                      SmokeableSpawner *spawner)
{
    printf("newvirgin %s %s %s\n", label(v), label(spawner), where());
    v->Static.Body._vtable = REC_IMAGE;
    return v;
}

static SmokeableInfo *infos[MAX_LIST];
static int ninfos;

SmokeableInfo *find_smokeable_info(uint32_t hash)
{
    int i;

    printf("findinfo %08x %s\n", (unsigned)hash, where());
    for (i = 0; i < ninfos; i++)
        if (infos[i]->NameHash == hash)
            return infos[i];
    return NULL;
}

Smokeable *smokeable_create(int32_t type, int32_t id, SmokeableInfo *info,
                            uint32_t name_hash)
{
    Smokeable *sm;

    printf("createsmokeable type=%d id=%d info=%s hash=%08x %s\n",
           (int)(type & 0xff), (int)id, label(info), (unsigned)name_hash,
           where());
    sm = make('S', "Smokeable");
    sm->Dynamic.Body._vtable = REC_IMAGE;
    return sm;
}

TrackPolygonCollisionBody *trackpolygoncollisionbody_init(
    TrackPolygonCollisionBody *t, int32_t id, TopologyTreePolygon *p)
{
    printf("newtpbody %s id=%d poly=%s %s\n", label(t), (int)id, label(p),
           where());
    t->Static.Body._vtable = REC_IMAGE;
    return t;
}

static CollisionBody *btab[MAX_LIST];
static int nbtab;

CollisionBody *collisionbody_find(int32_t i)
{
    int k;

    printf("findbody %d %s\n", (int)i, where());
    for (k = 0; k < nbtab; k++)
        if (btab[k]->ID == i)
            return btab[k];
    return NULL;
}

CollisionBodyWitness *cbwitness_init(CollisionBodyWitness *w,
                                     CollisionBody *b1, CollisionBody *b2)
{
    printf("newwitness %s %s %s %s\n", label(w), label(b1), label(b2),
           where());
    return w;
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

    if (!strcmp(fn, "virgin"))
        virginsmokeable_do_snapshot(p, s);
    else if (!strcmp(fn, "smokeable"))
        smokeable_do_snapshot(p, s);
    else if (!strcmp(fn, "world"))
        world_do_snapshot(p, s);
    else
        die("no function", fn);
}

// The ones with no object.
static void gcall(const char *fn)
{
    ReplaySnapshot *s = &snap;

    if (!strcmp(fn, "allsmokeables"))
        snapshot_all_smokeables(s);
    else if (!strcmp(fn, "tpbodies"))
        trackpolygoncollisionbody_snapshot_everything(s);
    else if (!strcmp(fn, "bodies"))
        collisionbody_snapshot_everything(s);
    else if (!strcmp(fn, "witnesses"))
        cbwitness_snapshot_everything(s);
    else if (!strcmp(fn, "cops"))
        snapshot_cops(s);
    else if (!strcmp(fn, "racecoord"))
        racecoordinator_do_snapshot(NULL, s);
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

// a,b,c or "-": the objects, in order.
static int refs(char *list, void **out)
{
    int n = 0;
    char *p = list;

    while (p && *p && strcmp(p, "-")) {
        char *c = strchr(p, ',');
        Obj *ob;

        if (c)
            *c++ = 0;
        if (n == MAX_LIST)
            die("list too long at", p);
        out[n++] = ref(p, &ob);
        p = c;
    }
    return n;
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
    } else if (!strcmp(o, "cbchain")) {
        // The list head, then the bodies, each linked to its neighbours.
        void *l[MAX_LIST + 1];
        int k, m;

        l[0] = &CollisionBodyList;
        m = refs(a[1], l + 1) + 1;
        for (k = 0; k < m; k++) {
            CollisionBodyNode *nd = l[k];

            nd->next = l[(k + 1) % m];
            nd->prev = l[(k + m - 1) % m];
        }
    } else if (!strcmp(o, "witchain")) {
        void *l[MAX_LIST + 1];
        int k, m;

        l[0] = &CollisionBodyWitnessList;
        m = refs(a[1], l + 1) + 1;
        for (k = 0; k < m; k++) {
            CollisionBodyWitnessNode *nd = l[k];

            nd->next = l[(k + 1) % m];
            nd->prev = l[(k + m - 1) % m];
        }
    } else if (!strcmp(o, "btab")) {
        nbtab = refs(a[1], (void **)btab);
    } else if (!strcmp(o, "infos")) {
        ninfos = refs(a[1], (void **)infos);
    } else if (!strcmp(o, "pools")) {
        VirginSmokeableSlotPool = addr(a[1]);
        TrackPolygonCollisionBodySlotPool = addr(a[2]);
        CollisionBodyWitnessSlotPool = addr(a[3]);
    } else if (!strcmp(o, "spawners")) {
        pSmokeableSpawners = addr(a[1]);
    } else if (!strcmp(o, "polytable")) {
        TheTopologyTree.pPolygonTable = addr(a[1]);
    } else if (!strcmp(o, "curworld")) {
        pCurrentWorld = addr(a[1]);
    } else if (!strcmp(o, "currace")) {
        pCurrentRace = addr(a[1]);
    } else if (!strcmp(o, "players")) {
        void *l[MAX_LIST];
        int k, m = refs(a[1], l);

        PlayerNumPlayers = m;
        for (k = 0; k < 2; k++)
            PlayerPlayersByIndex[k] = k < m ? l[k] : NULL;
    } else if (!strcmp(o, "graph")) {
        TheTrackGraph = addr(a[1]);
    } else if (!strcmp(o, "cops")) {
        pCopManager = addr(a[1]);
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
    } else if (!strcmp(o, "gcall")) {
        gcall(a[1]);
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
        die("usage:", "worldsnap_test script.txt");
    f = fopen(argv[1], "rb");
    if (f == NULL)
        die("cannot open", argv[1]);
    // A crash keeps everything printed before it.
    setvbuf(stdout, NULL, _IOLBF, 0);

    vt_install(REC_IMAGE, rec_vt, 32);
    gFlushClansFn = h_flushclans;
    gFlushFernShakersFn = h_flushferns;
    gCopManagerDoSnapshotFn = h_copmanager;
    gChopperDoSnapshotFn = h_chopper;
    // The globals, as the model registers them.
    add("cblist", &CollisionBodyList, NULL, 1, sizeof CollisionBodyList);
    add("witlist", &CollisionBodyWitnessList, NULL, 1,
        sizeof CollisionBodyWitnessList);
    add("cstats", &TheCollisionStats, NULL, 1, 72);
    add("awake", &AwakeSmokeablesCount, NULL, 1, 4);
    add("glare", &bResetGlare, NULL, 1, 4);
    add("fx", &WorldEffects, NULL, 1, 4);
    CollisionBodyList.next = CollisionBodyList.prev =
        (CollisionBody *)(void *)&CollisionBodyList;
    CollisionBodyWitnessList.next = CollisionBodyWitnessList.prev =
        (CollisionBodyWitness *)(void *)&CollisionBodyWitnessList;

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
