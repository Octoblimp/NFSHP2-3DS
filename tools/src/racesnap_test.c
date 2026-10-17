// racesnap_test -- the harness of tools/racesnap_check.py (TASKS 72d): the
// replay's DoSnapshots for the race's setup, the clock, the joystick, the
// camera shakers, the NIS manager, the traffic, the track graph, the race,
// its racing cars and the players, over a script.
//
// The same shape as aisnap_test.c, which it copies the ops of:
// tools/racesnap_check.py writes each record's field table in at the marker
// below -- name, host offset, host size, kind -- from the port's headers,
// so a script line names a field and each side writes and dumps it at its
// own offset. A pointer prints as the object and field it points into. The
// model (retail's code in mipsemu) reads the same script and must print
// the same lines.
//
// Recorded here, as the model's stubs print them: SetInputMode, the
// character lookup, and the NIS player's Load, StopAnimating and
// StartAnimating and the resource service. What the linked files reach
// outside the snapshots comes from racesnap_stubs.c and
// racesnap_stubdata.c, which `racesnap_check.py --stubs` writes; each of
// those functions stops the run.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "average.h"
#include "car.h"
#include "characterinfo.h"
#include "joyevent.h"
#include "joystick.h"
#include "nismanager.h"
#include "p32.h"
#include "physicscar.h"
#include "player.h"
#include "playerinput.h"
#include "playersettings.h"
#include "race.h"
#include "racecore.h"
#include "raceparams.h"
#include "realtime.h"
#include "replay.h"
#include "shake.h"
#include "trackgraph.h"
#include "trafficcar.h"
#include "traffictele.h"
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
#error "built from tools/racesnap_check.py, which writes the field tables in"
#endif

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

static void die(const char *what, const char *arg)
{
    fprintf(stderr, "racesnap_test: %s %s\n", what, arg);
    exit(2);
}

static const struct { const char *name; uint32_t image; } vts[] = {
    {"TrafficCar", TRAFFICCAR_VTABLE},
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

// ----------------------------------------------------------------- stubs
//
// What the model stubs in retail, here as lines both print.

// SetInputMode, 0x001776b0; playerinput.c would bring the cameras in.
void player_set_input_mode(struct Player *p, int32_t mode)
{
    printf("setinputmode %s %d\n", label(p), (int)mode);
}

// GetCharacterInfo, 0x001d9590: a place in the `chars` block, 16 bytes a
// character, so a pointer prints the same on both sides.
CharacterInfo *get_character_info(int32_t i)
{
    printf("charinfo %d\n", (int)i);
    return (CharacterInfo *)(find_obj("chars")->base + 16 * (i & 0xff));
}

// CarMover::DoSnapshot, retail's `jr ra`; physicscar.c holds the port's,
// with the whole PhysicsCar behind it.
void carmover_do_snapshot(CarMover *m, void *snap)
{
    (void)m;
    (void)snap;
}

// The NIS player's: Load sets LoadingNisNumber as the real one does, and
// the resource service finishes the last load.
static NisManager *nis_last;

static void h_nis_load(NisManager *m, int32_t nis)
{
    printf("nisload %s %d\n", label(m), (int)nis);
    m->LoadingNisNumber = nis;
    nis_last = m;
}

static int32_t h_nis_service(void)
{
    printf("nisservice\n");
    nis_last->LoadingNisNumber = -1;
    return 0;
}

static void h_nis_stop(NisManager *m)
{
    printf("nisstop %s\n", label(m));
}

static void h_nis_start(NisManager *m)
{
    printf("nisstart %s\n", label(m));
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

static void call(const char *fn, void *p)
{
    ReplaySnapshot *s = &snap;

    if (!strcmp(fn, "rideinfo"))
        ride_info_do_snapshot(p, s);
    else if (!strcmp(fn, "driverinfo"))
        driver_info_do_snapshot(p, s);
    else if (!strcmp(fn, "raceparams"))
        race_parameters_do_snapshot(p, s);
    else if (!strcmp(fn, "playersettings"))
        player_settings_do_snapshot(p, s);
    else if (!strcmp(fn, "tshaker"))
        tshaker_do_snapshot(p, s);
    else if (!strcmp(fn, "nismanager"))
        nismanager_do_snapshot(p, s);
    else if (!strcmp(fn, "trafficcar"))
        trafficcar_do_snapshot(p, s);
    else if (!strcmp(fn, "traffictele"))
        traffic_teleporter_do_snapshot(p, s);
    else if (!strcmp(fn, "trackgraph"))
        trackgraph_do_snapshot(p, s);
    else if (!strcmp(fn, "racingcar"))
        racing_car_do_snapshot(p, s);
    else if (!strcmp(fn, "race"))
        race_do_snapshot(p, s);
    else if (!strcmp(fn, "player"))
        player_do_snapshot(p, s);
    else
        die("no function", fn);
}

// The ones with no object.
static void gcall(const char *fn)
{
    if (!strcmp(fn, "worldtime"))
        WorldTimeDoSnapshot(&snap);
    else if (!strcmp(fn, "joystick"))
        JoystickDoSnapshot(&snap);
    else if (!strcmp(fn, "shakers"))
        snapshot_camera_shakers(&snap);
    else
        die("no function", fn);
}

typedef void (*SnapFn)(void *self, ReplaySnapshot *s);

// Through the record's table: the vptr at `path`, the entry at `slot`.
static void vcall(char **a)
{
    Obj *ob;
    uint8_t *at = ref(a[0], &ob);
    const CsField *f = find_field(ob->cls, a[1]);
    uint32_t v;
    const VtEntry *e;

    if (f->kind != 'V')
        die("vcall: not a vptr:", a[1]);
    memcpy(&v, at + f->off, 4);
    e = vt_slot(v, atoi(a[2]));
    ((SnapFn)e->fn)(vt_this(at, e), &snap);
}

// The clock's seven words, in retail's order from gp-19576.
static void *const wt_words[7] = {
    &WorldTimer, &WorldTimeSeconds, &WorldTime, &WorldTimeFrames,
    &WorldTimeElapsed, &WorldTimeElapsedFrame, &WorldLoopCounter,
};

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
    } else if (!strcmp(o, "global")) {
        // global|id: one of the snapshots' globals, by its retail name.
        if (!strcmp(a[1], "joy"))
            add("joy", CurrentJoystickTypes, NULL, 1, 2);
        else if (!strcmp(a[1], "env"))
            add("env", &ShakeAmplitudeEnvelope, NULL, 1, 4);
        else if (!strcmp(a[1], "shakers"))
            add("shakers", CameraShakers, find_class("tShaker"), 2,
                sizeof(tShaker));
        else if (!strcmp(a[1], "trp"))
            add("trp", &TheRaceParameters, find_class("RaceParameters"), 1,
                sizeof(RaceParameters));
        else
            die("no global", a[1]);
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
    } else if (!strcmp(o, "race")) {
        pCurrentRace = (Race *)ref(a[1], &ob);
    } else if (!strcmp(o, "timer")) {
        WorldTimer = atoi(a[1]);
        WorldLoopCounter = atoi(a[2]);
    } else if (!strcmp(o, "wtset")) {
        int i;

        if (unhex(a[1], buf, sizeof buf) != 28)
            die("wtset: not 28 bytes:", a[1]);
        for (i = 0; i < 7; i++)
            memcpy(wt_words[i], buf + 4 * i, 4);
    } else if (!strcmp(o, "wtdump")) {
        int i;

        for (i = 0; i < 7; i++)
            memcpy(buf + 4 * i, wt_words[i], 4);
        printf("wt = ");
        hex(buf, 28);
        printf("\n");
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
    } else if (!strcmp(o, "vcall")) {
        vcall(a + 1);
    } else if (!strcmp(o, "dump")) {
        dump_obj(find_obj(a[1]));
    } else if (!strcmp(o, "dumpp")) {
        printf("%s %s -> %s\n", a[1], a[2], label(*ptr_at(a[1], a[2])));
    } else {
        die("no op", o);
    }
    (void)n;
}

int main(int argc, char **argv)
{
    static char line[16384];
    FILE *f;

    if (argc != 2)
        die("usage:", "racesnap_test script.txt");
    f = fopen(argv[1], "rb");
    if (f == NULL)
        die("cannot open", argv[1]);
    // A crash keeps everything printed before it.
    setvbuf(stdout, NULL, _IOLBF, 0);

    trafficcar_install_vtables();
    gNisManagerLoadFn = h_nis_load;
    gNisServiceResourceLoadingFn = h_nis_service;
    gNisStopAnimatingFn = h_nis_stop;
    gNisStartAnimatingFn = h_nis_start;

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
