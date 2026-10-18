// carsnap_test -- the harness of tools/carsnap_check.py (TASKS 72b): the
// replay's DoSnapshots for the cars and their physics, over a script.
//
// tools/carsnap_check.py writes each record's field table in at the
// marker below -- name, host offset, host size, kind -- from the port's
// headers, so a script line names a field and each side writes and dumps
// it at its own offset. A pointer prints as the object and field it points
// into. The checker's docstring lists the ops; the model (retail's code in
// mipsemu) reads the same script and must print the same lines.
//
// Recorded here, as the model's stubs print them: a recording vtable,
// ClearInterestBBox, SetControlMode, SetMovementMode, SwitchSkin,
// UpdateCarReplacementTextures, AnimatedDriver's snapshot, the new
// Collision.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "aerodynamics.h"
#include "car.h"
#include "carcontroller.h"
#include "cardamage.h"
#include "cardriver.h"
#include "carrenderinfo.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "collision.h"
#include "collisionbody.h"
#include "copmanager.h"
#include "drivetrain.h"
#include "engine.h"
#include "epositionmarker.h"
#include "espresso.h"
#include "graph.h"
#include "joystick.h"
#include "p32.h"
#include "physcomp.h"
#include "physicscar.h"
#include "polyhedra.h"
#include "quickspline.h"
#include "race.h"
#include "realtime.h"
#include "replay.h"
#include "rigidbody.h"
#include "steering.h"
#include "suspension.h"
#include "terraintype.h"
#include "topology.h"
#include "trackpath.h"
#include "vclip.h"
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

// @FIELDS@

#ifndef CS_GENERATED
#error "built from tools/carsnap_check.py, which writes the field tables in"
#endif

#define REC_IMAGE 0x7e000000u
#define MAX_OBJS  512

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
static int            ncoll;

static const struct { const char *name; uint32_t image; } vts[] = {
    {"rec", REC_IMAGE},
    {"Ackerman", ACKERMAN_VTABLE},
    {"PhysicsCar", PHYSICSCAR_VTABLE},
    {"PhysicsCarVehicle", PHYSICSCAR_VEHICLE_VTABLE},
    {"CollisionBody", COLLISIONBODY_VTABLE},
    {"Static", STATICCOLLISIONBODY_VTABLE},
    {"TrackPolygon", TRACKPOLYGONCOLLISIONBODY_VTABLE},
    {"Dynamic", DYNAMICCOLLISIONBODY_VTABLE},
    {"CarCollisionBody", CARCOLLISIONBODY_VTABLE},
};

static void die(const char *what, const char *arg)
{
    fprintf(stderr, "carsnap_test: %s %s\n", what, arg);
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

void topology_clear_interest_bbox(TopologyCoordinate *tc)
{
    printf("clearbbox %s\n", label(tc));
}

void car_set_control_mode(Car *c, ControlMode mode)
{
    printf("setcontrol %s %d\n", label(c), (int)mode);
}

void car_set_movement_mode(Car *c, MovementMode mode)
{
    printf("setmovement %s %d\n", label(c), (int)mode);
}

void car_switch_skin(Car *c, uint32_t skin)
{
    printf("switchskin %s %d\n", label(c), (int)(int32_t)skin);
}

void carrenderinfo_update_car_replacement_textures(CarRenderInfo *ri)
{
    printf("replacetex %s\n", label(ri));
}

static void animdriver_snapshot(AnimatedDriver *d, ReplaySnapshot *s)
{
    printf("animdriver %s s=%s %s\n", label(d),
           s == &snap ? "snap" : "?", where());
}

static struct Collision *new_collision(CollisionBodyWitness *w, bVector3 *pt)
{
    const CsClass *c = find_class("Collision");
    char id[16];
    void *p = calloc(1, c->size);

    snprintf(id, sizeof id, "N%d", ncoll++);
    add(id, p, c, 1, c->size);
    printf("newcollision w=%s pt=%s\n", label(w), label(pt));
    return p;
}

// ------------------------------------------------------------ link stand-ins

// The clock's globals, which the timer op sets; realtime.c would bring the
// joylog in behind it.
int32_t WorldTimer;
int32_t WorldLoopCounter;
float   WorldTimeElapsed;

// What the linked files reach outside the snapshots. Nothing a scenario
// runs gets here, so each stops the run.
static void unreached(const char *what)
{
    fprintf(stderr, "%s reached\n", what);
    exit(3);
}

float              TestRPM;
Race              *pCurrentRace;
World             *pCurrentWorld;
RaceCoordinator   *pRaceCoordinator;
tCopManager       *pCopManager;
RaceParameters     TheRaceParameters;
TopologyTree       TheTopologyTree;
TerrainTypeInfo    TerrainTypeInfoTable[NUM_TERRAIN_TYPES];
CarTriggerEffectFn gCarTriggerEffectFn;

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wunused-parameter"
#define UNREACHED(ret, name, args) \
    ret name args { unreached(#name); for (;;) {} }
UNREACHED(int32_t, car_is_blinking, (Car *c))
UNREACHED(int32_t, car_is_poofed, (Car *c))
UNREACHED(float, car_move, (Car *c, float dt))
UNREACHED(void, car_set_to_physics_mode, (Car *c, Car *other))
UNREACHED(float, car_get_post_collision_yaw_control_boost, (Car *c))
UNREACHED(int32_t, car_should_visual_effects_be_generated, (Car *c))
UNREACHED(void, cardriver_init, (CarDriver *d))
UNREACHED(PipelinePolyhedron *, find_pipeline_polyhedron,
          (uint32_t name_hash, bVector3 *cog))
UNREACHED(RectPolyhedron *, rectpoly_init,
          (RectPolyhedron *r, float xmax, float xmin, float ymax, float ymin,
           float zmax, float zmin))
UNREACHED(void, waferpoly_init,
          (WaferPolyhedron *w, const TrackPolygon *tp, const bVector3 *origin))
UNREACHED(void, waferpoly_destroy, (WaferPolyhedron *w, int32_t flags))
UNREACHED(RCState, racecoordinator_get_current_state,
          (const RaceCoordinator *rc))
UNREACHED(int32_t, racecoordinator_is_replay_demo_mode,
          (const RaceCoordinator *rc))
UNREACHED(eRaceStage, race_get_race_stage, (const Race *r))
UNREACHED(float, world_get_distance_to_closest_player,
          (const World *w, const bVector3 *p))
UNREACHED(float, world_get_distance_to_closest_player_2d,
          (const World *w, const bVector2 *p))
UNREACHED(TrackPolygon *, topotree_assign,
          (TopologyTree *t, TopologyTreePolygon *p))
UNREACHED(void, topotree_unassign, (TopologyTree *t, TrackPolygon *tp))
UNREACHED(int32_t, IsJoystickTypeWheel, (JoystickPort port))
UNREACHED(Graph *, graph_init,
          (Graph *g, const bVector2 *points, int32_t count))
UNREACHED(float, graph_get_value, (Graph *g, float x))
UNREACHED(QuickSpline *, quickspline_init,
          (QuickSpline *s, QuickSplineEndPointType ept,
           QuickSplineBasisType basis, int32_t n))
UNREACHED(void, quickspline_destroy, (QuickSpline *s, int32_t flags))
UNREACHED(void, quickspline_set_num_control_points,
          (QuickSpline *s, int32_t n))
UNREACHED(void, quickspline_calibrate_length, (QuickSpline *s, int32_t samples))
UNREACHED(float, quickspline_find_closest_param,
          (QuickSpline *s, const bVector3 *p, float guess, float tolerance))
UNREACHED(bVector4 *, quickspline_get_point,
          (QuickSpline *s, bVector4 *out, float t, int32_t basis))
UNREACHED(ePositionMarker *, eFindPositionMarker,
          (uint32_t name_hash, uint32_t type_hash, ePositionMarker *prev))
UNREACHED(void, collision_sound_play_glass, (const bVector3 *pos))
UNREACHED(void, emodel_set_environment_mapping,
          (eModel *m, uint32_t hash, int32_t on))
UNREACHED(void *, esp_create_object, (const char *layer, const char *type))
UNREACHED(void, esp_delete_object, (void *obj))
UNREACHED(void, esp_create_user_mesh, (void *obj, int32_t faces))
UNREACHED(void, esp_set_user_mesh_face,
          (void *obj, int32_t face, FloatVector *verts))
UNREACHED(void, esp_set_object_position, (void *obj, bVector3 *pos))
#undef UNREACHED
#pragma GCC diagnostic pop

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

static void dumpg(void)
{
    uint32_t w;

    memcpy(&w, &MaxCollisionBodyWidthX, 4);
    printf("globals stats=%d,%d maxw=%08x cblist=%s,%s\n",
           (int)TheCollisionStats.NumCollisions,
           (int)TheCollisionStats.HighestNumCollisions, (unsigned)w,
           label(CollisionBodyList.next), label(CollisionBodyList.prev));
}

// ------------------------------------------------------------------ calls

typedef void (*SnapFn)(void *self, ReplaySnapshot *s);

static void call(const char *fn, void *p)
{
    ReplaySnapshot *s = &snap;

    if (!strcmp(fn, "rigidbody"))
        rigidbody_do_snapshot(p, s);
    else if (!strcmp(fn, "wheel"))
        wheel_do_snapshot(p, s);
    else if (!strcmp(fn, "suspension"))
        suspension_do_snapshot(p, s);
    else if (!strcmp(fn, "engine"))
        engine_do_snapshot(p, s);
    else if (!strcmp(fn, "drivetrain"))
        drivetrain_do_snapshot(p, s);
    else if (!strcmp(fn, "aero"))
        aerodynamics_do_snapshot(p, s);
    else if (!strcmp(fn, "ackerman"))
        ackerman_do_snapshot(p, s);
    else if (!strcmp(fn, "physicscar"))
        physicscar_do_snapshot(p, s);
    else if (!strcmp(fn, "carmover"))
        carmover_do_snapshot(p, s);
    else if (!strcmp(fn, "carstate"))
        carstate_do_snapshot(p, s);
    else if (!strcmp(fn, "bodydamage"))
        bodydamage_do_snapshot(p, s);
    else if (!strcmp(fn, "cardamage"))
        cardamage_do_snapshot(p, s);
    else if (!strcmp(fn, "collisionbody"))
        collisionbody_do_snapshot(p, s);
    else if (!strcmp(fn, "staticbody")) {
        // Through StaticCollisionBody's table, as the jump is retail's.
        CollisionBody *b = p;
        const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_DO_SNAPSHOT);

        ((SnapFn)e->fn)(vt_this(b, e), s);
    } else if (!strcmp(fn, "trackpolygon"))
        trackpolygoncollisionbody_do_snapshot(p, s);
    else if (!strcmp(fn, "dynamic"))
        dynamiccollisionbody_do_snapshot(p, s);
    else if (!strcmp(fn, "carcollisionbody"))
        carcollisionbody_do_snapshot(p, s);
    else if (!strcmp(fn, "cbwitness"))
        cbwitness_do_snapshot(p, s);
    else if (!strcmp(fn, "vcwitness"))
        vcwitness_do_snapshot(p, s);
    else if (!strcmp(fn, "collision"))
        collision_do_snapshot(p, s);
    else if (!strcmp(fn, "tpcoord"))
        trackpath_coord_do_snapshot(p, s);
    else if (!strcmp(fn, "carcontroller"))
        carcontroller_do_snapshot(p, s);
    else if (!strcmp(fn, "car"))
        car_do_snapshot(p, s);
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

static void op(char **a, int n)
{
    const char *o = a[0];
    Obj *ob, *ob2;
    uint8_t *at, *at2, buf[256];

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
        const CsField *f;
        void *v = NULL;

        at = ref(a[1], &ob);
        f = find_field(ob->cls, a[2]);
        if (f->kind != 'P')
            die("link: not a pointer:", a[2]);
        if (strcmp(a[3], "0")) {
            at2 = ref(a[3], &ob2);
            v = at2;
            if (strcmp(a[4], "-"))
                v = at2 + path_off(ob2->cls, a[4]);
        }
        memcpy(at + f->off, &v, sizeof v);
    } else if (!strcmp(o, "vt")) {
        const CsField *f;
        uint32_t v = vt_image(a[3]);

        at = ref(a[1], &ob);
        f = find_field(ob->cls, a[2]);
        if (f->kind != 'V')
            die("vt: not a vptr:", a[2]);
        memcpy(at + f->off, &v, 4);
    } else if (!strcmp(o, "cblist")) {
        CollisionBody *b = (CollisionBody *)ref(a[1], &ob);

        CollisionBodyList.next = b;
        CollisionBodyList.prev = b;
        b->Link.next = (CollisionBody *)(void *)&CollisionBodyList;
        b->Link.prev = (CollisionBody *)(void *)&CollisionBodyList;
    } else if (!strcmp(o, "tpm")) {
        TheTrackPathManager.pPoints = (TrackPathPoint *)ref(a[1], &ob);
    } else if (!strcmp(o, "stats")) {
        TheCollisionStats.NumCollisions = atoi(a[1]);
        TheCollisionStats.HighestNumCollisions = atoi(a[2]);
    } else if (!strcmp(o, "maxw")) {
        unhex(a[1], buf, 4);
        memcpy(&MaxCollisionBodyWidthX, buf, 4);
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
    } else if (!strcmp(o, "dumpn")) {
        int i;

        for (i = 0; i < nobjs; i++)
            if (objs[i].id[0] == 'N' && objs[i].id[1] >= '0'
                && objs[i].id[1] <= '9')
                dump_obj(&objs[i]);
    } else if (!strcmp(o, "dumpg")) {
        dumpg();
    } else if (!strcmp(o, "usage")) {
        at = ref(a[1], &ob);
        if (ob->size < sizeof(CarTypeInfo))
            die("usage: too small for a CarTypeInfo:", a[1]);
        ((CarTypeInfo *)at)->UsageType = atoi(a[2]);
    } else if (!strcmp(o, "rdriver")) {
        // The port's car keeps no driver; the flag is what the stand-in
        // reads (car.h, gCarSnapshotRetailDrivers).
        static int32_t retail_drivers;

        (void)ref(a[1], &ob);
        (void)ref(a[2], &ob2);
        retail_drivers = atoi(a[3]);
        gCarSnapshotRetailDrivers = &retail_drivers;
    } else {
        die("no op", o);
    }
}

int main(int argc, char **argv)
{
    static char line[8192];
    FILE *f;

    if (argc != 2)
        die("usage:", "carsnap_test script.txt");
    f = fopen(argv[1], "rb");
    if (f == NULL)
        die("cannot open", argv[1]);
    // A crash keeps everything printed before it.
    setvbuf(stdout, NULL, _IOLBF, 0);

    physcomp_install_vtables();
    physicscar_install_vtables();
    collisionbody_install_vtables();
    carcollisionbody_install_vtable();
    vt_install(REC_IMAGE, rec_vt, 32);
    gAnimatedDriverDoSnapshotFn = animdriver_snapshot;
    gCollisionNewFn = new_collision;
    gCollisionDoSnapshotFn = collision_do_snapshot;
    add("cblist", &CollisionBodyList, NULL, 1, 8);

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
