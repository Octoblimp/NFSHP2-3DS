// Harness for tools/copdriver_check.py: runs the checker's script on the
// port's CopDriver (copdriver.c) and prints what the model prints for the
// image. The ops, their arguments and every line's format are the
// checker's; this file only carries them out, and stands in for what the
// checker stubs.
//
//     copdriver_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "car.h"
#include "cardriver.h"
#include "carmodes.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "collision.h"
#include "collisionbody.h"
#include "cop.h"
#include "copdriver.h"
#include "copmanager.h"
#include "drivetarget.h"
#include "realcontroller.h"
#include "topology.h"
#include "trackroute.h"
#include "vtable.h"

// ------------------------------------------------------------- the world

#define COP_SLOT 3

static union {
    CopDriver     d;
    unsigned char b[sizeof(CopDriver)];
} cdu;
static CopDriver *const cd = &cdu.d;

static union {
    NullDriver    n;
    unsigned char b[sizeof(NullDriver)];
} ndu;
static NullDriver *const nd = &ndu.n;

static Car              carc, carh;
static CarTypeInfo      ctic, ctih;
static CopMover         mvr;
static CarCollisionBody dcbc, dcbh;
static tAICop           aic;
static tPursuit         pur;
static tCopManager      mgr;
static TrackRoutePoint  rpc, rph;
static unsigned char    player_c[64], player_h[64];
static bVector2         outv;
static float            outl;

// carmodes.c's seams, which the install functions set.
CarMoverCtorFn      gCopMoverCtorFn;
CarControllerCtorFn gCopDriverCtorFn;

// What the IsNearPursuitTarget stand-in answers.
static int32_t near_answer;

static float fbits(uint32_t b)
{
    float f;

    memcpy(&f, &b, 4);
    return f;
}

static uint32_t bitsf(float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    return b;
}

// A float's bits, or "nan" for any NaN.
static const char *hx(uint32_t b)
{
    static char bufs[16][12];
    static int k;
    char *s = bufs[k++ & 15];

    if ((b & 0x7f800000u) == 0x7f800000u && (b & 0x007fffffu) != 0)
        snprintf(s, 12, "nan");
    else
        snprintf(s, 12, "%08x", b);
    return s;
}

static const char *fx(float f)
{
    return hx(bitsf(f));
}

static const char *lab(const void *a)
{
    if (a == NULL)
        return "null";
    if (a == (const void *)cd)
        return "cd";
    if (a == (const void *)&cd->v2SteerTarget)
        return "cd.st";
    if (a == (const void *)nd)
        return "nd";
    if (a == (const void *)&carc)
        return "cop";
    if (a == (const void *)&carh)
        return "ch";
    if (a == (const void *)&carc.State.Position)
        return "cop.pos";
    if (a == (const void *)&carh.State.Position)
        return "ch.pos";
    if (a == (const void *)&aic)
        return "aic";
    if (a == (const void *)&pur.FarDriveTarget)
        return "far";
    if (a == (const void *)&pur.NearDriveTarget)
        return "near";
    if (a == (const void *)&mvr)
        return "mv";
    if (a == (const void *)&rpc)
        return "rpc";
    if (a == (const void *)&rph)
        return "rph";
    if (a == (const void *)&outv)
        return "out";
    return "?";
}

static const char *vtname(uint32_t v)
{
    static char buf[4][12];
    static int k;
    char *s;

    if (v == COPDRIVER_VTABLE)
        return "copdriver";
    if (v == NULLDRIVER_VTABLE)
        return "nulldriver";
    if (v == CARDRIVER_VTABLE)
        return "cardriver";
    s = buf[k++ & 3];
    snprintf(s, 12, "%08x", v);
    return s;
}

// ------------------------------------------------------------ stand-ins

void *bMalloc(int size, const char *name, int a, int pool)
{
    printf("  malloc %d %s %d %d\n", size, name, a, pool);
    return ndu.b;
}

static void never(const char *name);

void bFree(void *p)
{
    (void)p;
    never("bFree");
}

TrackedController *trackedcontroller_init(TrackedController *c, Car *car)
{
    printf("  tcinit %s %s\n", lab(c), lab(car));
    c->Base.pCar = car;
    return c;
}

void trackedcontroller_destroy(TrackedController *c, int32_t flags)
{
    printf("  tcdtor %s %d %s\n", lab(c), flags,
           vtname(c->Base._vtable));
}

void trackedcontroller_think(TrackedController *c, float dt)
{
    printf("  tcthink %s %s\n", lab(c), fx(dt));
}

static void never(const char *name)
{
    printf("  never %s\n", name);
    fflush(stdout);
    exit(4);
}

void trackedcontroller_set_current_route(TrackedController *c, TrackRoute *r,
                                         TrackRoutePoint *p)
{
    (void)c; (void)r; (void)p;
    never("set_current_route");
}

TrackRoute *trackedcontroller_get_current_route(TrackedController *c,
                                                int find)
{
    (void)c; (void)find;
    never("get_current_route");
    return NULL;
}

TrackRoutePoint *trackedcontroller_get_current_route_point(
    TrackedController *c, int find)
{
    (void)c; (void)find;
    never("get_current_route_point");
    return NULL;
}

float trackedcontroller_get_amount_out_of_bounds(TrackedController *c)
{
    (void)c;
    never("get_amount_out_of_bounds");
    return 0.0f;
}

void trackedcontroller_find_where_i_am(TrackedController *c)
{
    (void)c;
    never("find_where_i_am");
}

void trackedcontroller_just_reset(TrackedController *c)
{
    (void)c;
    never("just_reset");
}

void carcontroller_debug_display(CarController *c)
{
    (void)c;
    never("debug_display");
}

void carcontroller_set_to_physics_mode(CarController *c, Car *car)
{
    (void)c; (void)car;
    never("set_to_physics_mode");
}

void carcontroller_force_boost(CarController *c, float f)
{
    (void)c; (void)f;
    never("force_boost");
}

void carcontroller_release_boost(CarController *c)
{
    (void)c;
    never("release_boost");
}

DriveTarget *drivetarget_init(DriveTarget *t)
{
    printf("  dtinit %s %s\n", lab(t), vtname(((CarDriver *)t)->_vtable));
    return t;
}

void drivetarget_clear(DriveTarget *t, Car *car, float speed)
{
    printf("  dtclear %s %s %s %d\n", lab(t), lab(car), fx(speed),
           (int)((CarDriver *)t)->DesiredGear);
}

DriveTarget *drivetarget_assign(DriveTarget *dst, const DriveTarget *src)
{
    printf("  assign %s %s\n", lab(dst), lab(src));
    return dst;
}

TrackRoutePoint *car_get_route_point(Car *c, int find)
{
    printf("  rp %s %d\n", lab(c), find);
    if (c == &carc)
        return &rpc;
    if (c == &carh)
        return &rph;
    return NULL;
}

int32_t taicop_is_near_pursuit_target(const tAICop *c)
{
    printf("  near %s -> %d\n", lab(c), near_answer);
    return near_answer;
}

void taicop_initialize_drive_target(tAICop *c)
{
    printf("  init %s\n", lab(c));
}

void taicop_update_drive_target(tAICop *c, const bVector2 *pos,
                                int32_t keep)
{
    printf("  update %s %s %d\n", lab(c), lab(pos), keep);
}

// CopMover's, which CopDriver never reaches.
float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    (void)tc; (void)pt; (void)terrain; (void)normal; (void)found;
    never("elevation");
    return 0.0f;
}

void carstate_calculate_geometry_position(CarState *s)
{
    (void)s;
    never("geom");
}

void carstate_calculate_wheel_matrices(CarState *s)
{
    (void)s;
    never("wmat");
}

void carstate_set_wheel_touching_ground(CarState *s, int wheel, int8_t on)
{
    (void)s; (void)wheel; (void)on;
    never("touch");
}

void carstate_set_wheel_terrain(CarState *s, int wheel, TerrainType t)
{
    (void)s; (void)wheel; (void)t;
    never("terrain");
}

void car_compute_fake_rpm(Car *c)
{
    (void)c;
    never("rpm");
}

void carmover_destroy(CarMover *m, int32_t flags)
{
    (void)m; (void)flags;
    never("cmdtor");
}

// coputil.c's CarCausedRecentCollision's, which CopDriver doesn't call.
struct Collision *collisionbody_get_collision(CollisionBody *b, int32_t i)
{
    (void)b; (void)i;
    never("get_collision");
    return NULL;
}

int32_t collision_is_two_car_collision(Collision *c)
{
    (void)c;
    never("two_car_collision");
    return 0;
}

void collision_get_colliding_cars(Collision *c, Car **car1, Car **car2)
{
    (void)c; (void)car1; (void)car2;
    never("colliding_cars");
}

int32_t car_is_car_in_front(Car *c, Car *other, uint16_t angle)
{
    (void)c; (void)other; (void)angle;
    never("in_front");
    return 0;
}

// The NullDriver's table: its destructor and SetDesiredSpeed, logged.
static void nd_dtor(void *self, int32_t flags)
{
    printf("  nddtor %s %d\n", lab(self), flags);
}

static void nd_speed(void *self, float speed, float time, float tol,
                     int32_t allowed)
{
    printf("  ndspeed %s %s %s %s %d\n", lab(self), fx(speed), fx(time),
           fx(tol), allowed);
}

static VtEntry nd_vt[CARDRIVER_VT_ENTRIES];

// ------------------------------------------------------------ the fields

typedef struct Group {
    const char *name;
    void       *p;
    int         n;
    char        kind;   // f a float, h a u16, w a word, b a byte
} Group;

#define MAXG 16
#define NOBJ 12

static struct Obj {
    const char *name;
    Group       g[MAXG];
    int         n;
} objs[NOBJ];
static int nobjs;

static struct Obj *obj(const char *name)
{
    int i;

    for (i = 0; i < nobjs; i++)
        if (strcmp(objs[i].name, name) == 0)
            return &objs[i];
    objs[nobjs].name = name;
    return &objs[nobjs++];
}

static void add(const char *o, const char *name, void *p, int count,
                char kind)
{
    struct Obj *b = obj(o);

    b->g[b->n].name = name;
    b->g[b->n].p = p;
    b->g[b->n].n = count;
    b->g[b->n].kind = kind;
    b->n++;
}

static void groups(void)
{
    add("cd", "st", &cd->State, 3, 'w');
    add("cd", "tm", &cd->fStuckTimer, 3, 'f');
    add("cd", "idx", &cd->nCopIndex, 1, 'w');
    add("cd", "steer", &cd->v2SteerTarget.x, 2, 'f');
    add("cd", "cls", &cd->nCarClass, 1, 'w');

    add("mv", "face", &mvr.aFacingAngle, 2, 'h');
    add("mv", "spd", &mvr.fSpeed, 5, 'f');
    add("mv", "dvel", &mvr.v3DesiredVelocity.x, 3, 'f');
    add("mv", "st", &mvr.State, 1, 'w');

    add("nd", "steer", &nd->Base.Steering, 1, 'h');
    add("nd", "thr", &nd->Base.Throttle, 3, 'f');
    add("nd", "gear", &nd->Base.DesiredGear, 2, 'w');
    add("nd", "nitro", &nd->Base.NitroFlag, 1, 'w');

    add("cop", "pos", &carc.State.Position.x, 2, 'f');
    add("cop", "vel", &carc.State.Velocity.x, 2, 'f');
    add("cop", "angle", &carc.State.Angle, 1, 'h');
    add("cop", "fs", &carc.State.ForwardSpeed, 1, 'f');
    add("cop", "vm", &carc.State.VelocityMagnitude, 1, 'f');
    add("cop", "mode", &carc.TheMovementMode, 1, 'w');
    add("cop", "col", &dcbc.Dynamic.Body.NumCollisions, 1, 'b');

    add("ch", "pos", &carh.State.Position.x, 2, 'f');
    add("ch", "vel", &carh.State.Velocity.x, 2, 'f');
    add("ch", "angle", &carh.State.Angle, 1, 'h');
    add("ch", "fs", &carh.State.ForwardSpeed, 1, 'f');
    add("ch", "vm", &carh.State.VelocityMagnitude, 1, 'f');

    add("ctic", "type", &ctic.Type, 1, 'w');
    add("ctic", "cls", &ctic.CarClass, 1, 'b');
    add("ctih", "type", &ctih.Type, 1, 'w');
    add("ctih", "cls", &ctih.CarClass, 1, 'b');

    add("aic", "ls", &aic.Base.LogicState, 4, 'w');
    add("aic", "n48", &aic.New48.x, 2, 'f');

    add("rpc", "pos", &rpc.Position.x, 2, 'f');
    add("rpc", "dir", &rpc.Direction.x, 2, 'f');
    add("rpc", "spd", rpc.DrivingLineSpeeds, 21, 'b');
    add("rph", "pos", &rph.Position.x, 2, 'f');
    add("rph", "dir", &rph.Direction.x, 2, 'f');
    add("rph", "spd", rph.DrivingLineSpeeds, 21, 'b');
}

static Group *find(const char *o, const char *name)
{
    struct Obj *b = obj(o);
    int i;

    for (i = 0; i < b->n; i++)
        if (strcmp(b->g[i].name, name) == 0)
            return &b->g[i];
    fprintf(stderr, "no group %s.%s\n", o, name);
    exit(3);
}

static void poke(Group *g, int i, uint32_t v)
{
    if (g->kind == 'h')
        ((uint16_t *)g->p)[i] = (uint16_t)v;
    else if (g->kind == 'b')
        ((uint8_t *)g->p)[i] = (uint8_t)v;
    else
        memcpy((uint32_t *)g->p + i, &v, 4);
}

static void show(const char *o)
{
    struct Obj *b = obj(o);
    int i, k;

    for (i = 0; i < b->n; i++) {
        Group *g = &b->g[i];

        printf("  %s.%s", o, g->name);
        for (k = 0; k < g->n; k++) {
            if (g->kind == 'h') {
                printf(" %d", ((uint16_t *)g->p)[k]);
            } else if (g->kind == 'b') {
                printf(" %d", ((uint8_t *)g->p)[k]);
            } else {
                uint32_t v;
                memcpy(&v, (uint32_t *)g->p + k, 4);
                if (g->kind == 'f')
                    printf(" %s", hx(v));
                else
                    printf(" %08x", v);
            }
        }
        printf("\n");
    }
}

// ------------------------------------------------------------ the ops

static uint32_t num(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static DriveTarget *target(const char *s)
{
    if (strcmp(s, "far") == 0)
        return &pur.FarDriveTarget;
    if (strcmp(s, "near") == 0)
        return &pur.NearDriveTarget;
    if (strcmp(s, "nd") == 0)
        return &nd->Base.MyDriveTarget;
    fprintf(stderr, "no target %s\n", s);
    exit(3);
}

static Car *carnamed(const char *s)
{
    return strcmp(s, "cop") == 0 ? &carc : &carh;
}

static const VtEntry *cdslot(int32_t off)
{
    return vt_slot(cd->Base.Base._vtable, off);
}

typedef void (*DtorFn)(void *self, int32_t flags);
typedef void (*ThinkFn)(void *self, float dt);

static void op(char **a, int na)
{
    const char *o = a[0];

    if (strcmp(o, "tag") == 0) {
        printf("# %s\n", a[1]);
    } else if (strcmp(o, "set") == 0) {
        poke(find(a[1], a[2]), (int)num(a[3]), num(a[4]));
    } else if (strcmp(o, "lvl") == 0) {
        mgr.nDifficultyLevel = (int32_t)num(a[1]);
    } else if (strcmp(o, "near") == 0) {
        near_answer = (int32_t)num(a[1]);
    } else if (strcmp(o, "pursuit") == 0) {
        aic.Base.pMyPursuit = num(a[1]) ? &pur : NULL;
    } else if (strcmp(o, "player") == 0) {
        Car *c = carnamed(a[1]);

        c->pPlayer = num(a[2]) ? (Player *)(void *)(c == &carc ? player_c
                                                               : player_h)
                               : NULL;
    } else if (strcmp(o, "pts") == 0) {
        DriveTarget *t = target(a[1]);
        int n = (int)num(a[2]), i;

        t->NumPoints = (int8_t)n;
        for (i = 0; i < n && 3 + 4 * i + 3 < na; i++) {
            t->Points[i].x = fbits(num(a[3 + 4 * i]));
            t->Points[i].y = fbits(num(a[4 + 4 * i]));
            t->Points[i].z = fbits(num(a[5 + 4 * i]));
            t->Points[i].pad = fbits(num(a[6 + 4 * i]));
        }
    } else if (strcmp(o, "hist") == 0) {
        int n = (int)num(a[1]), i;

        pur.History.nCount = n;
        for (i = 0; i < n && i < 30; i++) {
            pur.History.v2Velocity[i].x = fbits(num(a[2 + 3 * i]));
            pur.History.v2Velocity[i].y = fbits(num(a[3 + 3 * i]));
            pur.History.fTime[i] = fbits(num(a[4 + 3 * i]));
        }
    } else if (strcmp(o, "new") == 0) {
        CarController *r;

        memset(cdu.b, 0xcd, sizeof cdu.b);
        memset(ndu.b, 0xab, sizeof ndu.b);
        r = gCopDriverCtorFn(cdu.b, &carc);
        printf("new -> %s\n", lab(r));
    } else if (strcmp(o, "del") == 0) {
        const VtEntry *e = cdslot(CARCONTROLLER_VT_DTOR);
        ((DtorFn)e->fn)(vt_this(cd, e), (int32_t)num(a[1]));
        printf("del\n");
    } else if (strcmp(o, "dtor") == 0) {
        cd->Base.Base._vtable = num(a[2]);
        copdriver_destroy(cd, (int32_t)num(a[1]));
        printf("dtor\n");
    } else if (strcmp(o, "nodrv") == 0) {
        cd->Base.Base.Driver = NULL;
    } else if (strcmp(o, "drv") == 0) {
        cd->Base.Base.Driver = &nd->Base;
    } else if (strcmp(o, "think") == 0) {
        const VtEntry *e = cdslot(CARCONTROLLER_VT_THINK);
        ((ThinkFn)e->fn)(vt_this(cd, e), fbits(num(a[1])));
        printf("think\n");
    } else if (strcmp(o, "gptp") == 0) {
        outv.x = fbits(0x41414141u);
        outv.y = fbits(0x42424242u);
        copdriver_get_pursuit_target_point(cd, &outv);
        printf("gptp -> %s %s\n", fx(outv.x), fx(outv.y));
    } else if (strcmp(o, "stuck") == 0) {
        int32_t r = copdriver_are_we_stuck(cd, fbits(num(a[1])));
        printf("stuck -> %d %s\n", (int)r, fx(cd->fStuckTimer));
    } else if (strcmp(o, "fpd") == 0) {
        DLOffset off;
        bVector2 pos;
        int32_t  r;

        pos.x = fbits(num(a[2]));
        pos.y = fbits(num(a[3]));
        off.x = fbits(num(a[5]));
        off.y = fbits(num(a[6]));
        outv.x = fbits(0x41414141u);
        outv.y = fbits(0x42424242u);
        outl = fbits(0x43434343u);
        r = copdriver_find_point_by_distance(&outv, &outl, target(a[1]),
                                             &pos, fbits(num(a[4])), &off);
        printf("fpd -> %d %s %s %s\n", (int)r, fx(outv.x), fx(outv.y),
               fx(outl));
    } else if (strcmp(o, "gpdl") == 0) {
        DLOffset off;

        off.x = fbits(num(a[2]));
        off.y = fbits(num(a[3]));
        outv.x = fbits(0x41414141u);
        outv.y = fbits(0x42424242u);
        copdriver_get_point_by_dl_offset_from_start(&outv, target(a[1]),
                                                    &off);
        printf("gpdl -> %s %s\n", fx(outv.x), fx(outv.y));
    } else if (strcmp(o, "grn") == 0) {
        copdriver_get_route_numbers_to_use(cd, NULL, NULL);
    } else if (strcmp(o, "sps") == 0) {
        copdriver_set_patrol_speed(cd, fbits(num(a[1])));
    } else if (strcmp(o, "sst") == 0) {
        copdriver_set_state(cd, (eCopDriverStates)num(a[1]));
    } else if (strcmp(o, "sci") == 0) {
        copdriver_set_cop_index(cd, (int32_t)num(a[1]));
    } else if (strcmp(o, "dump") == 0) {
        printf("dump\n");
        printf("  cd.ctl %s %s %s\n", lab(cd->Base.Base.pCar),
               lab(cd->Base.Base.Driver), vtname(cd->Base.Base._vtable));
        show("cd");
        show("mv");
        printf("  nd.vt %s\n", vtname(nd->Base._vtable));
        show("nd");
    } else {
        fprintf(stderr, "bad op %s (%d)\n", o, na);
        exit(3);
    }
}

int main(int argc, char **argv)
{
    static char line[1 << 14];
    FILE *f;

    if (argc != 2) {
        fprintf(stderr, "usage: copdriver_test script.txt\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    pCopManager = &mgr;
    mgr.Cops[COP_SLOT] = &aic.Base;
    aic.Base.pMyCar = &carc;
    pur.pChasedCar = &carh;
    carc.pCarTypeInfo = &ctic;
    carh.pCarTypeInfo = &ctih;
    carc.pCarMover = &mvr.Mover;
    mvr.pCar = &carc;
    carc.pCarDriver = &nd->Base;
    carc.pDynamicCollisionBody = &dcbc;
    carh.pDynamicCollisionBody = &dcbh;
    groups();
    vt_reset();
    copdriver_install_vtables();
    copdriver_install_seams();
    nd_vt[CARDRIVER_VT_DTOR / 8].fn = (VtFn)nd_dtor;
    nd_vt[CARDRIVER_VT_SET_DESIRED_SPEED / 8].fn = (VtFn)nd_speed;
    vt_install(NULLDRIVER_VTABLE, nd_vt, CARDRIVER_VT_ENTRIES);
    while (fgets(line, sizeof line, f) != NULL) {
        char *a[400], *s = line;
        int   na = 0;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        while (na < 400) {
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
