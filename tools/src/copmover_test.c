// Harness for tools/copmover_check.py: runs the checker's script on the
// port's CopMover (copdriver.c) and prints what the model prints for the
// image. The ops, their arguments and every line's format are the
// checker's; this file only carries them out, and stands in for what the
// checker stubs.
//
//     copmover_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "car.h"
#include "carcontroller.h"
#include "cardriver.h"
#include "carmodes.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "cop.h"
#include "copdriver.h"
#include "copmanager.h"
#include "coputil.h"
#include "drivetarget.h"
#include "realcontroller.h"
#include "topology.h"
#include "trackroute.h"
#include "vtable.h"

// ------------------------------------------------------------- the world

static union {
    CopMover      m;
    unsigned char b[sizeof(CopMover)];
} mvu;
static CopMover *const mv = &mvu.m;

static Car         car;
static CarTypeInfo cti;
static CarDriver   drv;
static tCopManager mgr;

// copmanager.c's, which the harness does not link.
tCopManager *pCopManager = &mgr;

// carmodes.c's seam, which copmover_install_seams sets.
CarMoverCtorFn gCopMoverCtorFn;

// The ground the GetElevation stand-in answers with: a plane, a step up
// past x = sx or below y = sy, and what it says it found.
static struct {
    float   gz, gx, gy, sx, sz, sy;
    int32_t found;
    float   n[4];
    int32_t terrain;
} ground;

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

// A float's bits, or "nan" for any NaN: the EE has none, and which one an
// IEEE host or the model makes is neither's to say.
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

static const char *lab(const void *a)
{
    if (a == NULL)
        return "null";
    if (a == (const void *)mv)
        return "mv";
    if (a == (const void *)&mv->v2TransverseAccel)
        return "ta";
    if (a == (const void *)&mv->v3GroundNormal)
        return "mvn";
    if (a == (const void *)&car)
        return "car";
    if (a == (const void *)&car.State)
        return "cs";
    if (a == (const void *)&car.TheTopologyCoordinate)
        return "tc";
    return "?";
}

// ------------------------------------------------------------ stand-ins

float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    float e = (ground.gx * pt->x + ground.gy * pt->y) + ground.gz;

    if (pt->x > ground.sx || pt->y < ground.sy)
        e = e + ground.sz;
    printf("  elev %s %s %s %s %s %s %s -> %s\n", lab(tc), hx(bitsf(pt->x)),
           hx(bitsf(pt->y)), hx(bitsf(pt->z)), terrain ? "t" : "-",
           lab(normal), found ? "f" : "-", hx(bitsf(e)));
    if (terrain != NULL)
        *terrain = ground.terrain;
    if (normal != NULL) {
        if (ground.found) {
            normal->x = ground.n[0];
            normal->y = ground.n[1];
            normal->z = ground.n[2];
            normal->pad = ground.n[3];
        } else {
            normal->x = 0.0f;
            normal->y = 0.0f;
            normal->z = -1.0f;
        }
    }
    if (found != NULL)
        *found = ground.found;
    return e;
}

void carstate_calculate_geometry_position(CarState *s)
{
    printf("  geom %s\n", lab(s));
}

void carstate_calculate_wheel_matrices(CarState *s)
{
    printf("  wmat %s\n", lab(s));
}

void carstate_set_wheel_touching_ground(CarState *s, int wheel, int8_t on)
{
    printf("  touch %s %d %d\n", lab(s), wheel, on);
}

void carstate_set_wheel_terrain(CarState *s, int wheel, TerrainType t)
{
    printf("  terrain %s %d %d\n", lab(s), wheel, (int)t);
}

void car_compute_fake_rpm(Car *c)
{
    printf("  rpm %s\n", lab(c));
}

void carmover_destroy(CarMover *m, int32_t flags)
{
    printf("  cmdtor %s %d %08x\n", lab(m), flags, (unsigned)m->_vtable);
}

// CopDriver's, the other half of copdriver.c (12d), which
// copdriver_check checks and this script never reaches.
CarControllerCtorFn gCopDriverCtorFn;

static void unreached(const char *f)
{
    fprintf(stderr, "copmover_test: %s reached\n", f);
    exit(3);
}

#define UNREACHED(ret, name, args)  ret name args { unreached(#name); exit(3); }

UNREACHED(void *, bMalloc, (int size, const char *name, int flags, int pool))
UNREACHED(TrackRoutePoint *, car_get_route_point, (Car *c, int find))
UNREACHED(int32_t, car_in_recent_collision, (struct Car *c))
UNREACHED(void, carcontroller_debug_display, (CarController *c))
UNREACHED(void, carcontroller_force_boost, (CarController *c, float f))
UNREACHED(void, carcontroller_release_boost, (CarController *c))
UNREACHED(void, carcontroller_set_to_physics_mode,
          (CarController *c, struct Car *k))
UNREACHED(void, cardriver_init, (CarDriver *d))
UNREACHED(DriveTarget *, drivetarget_assign,
          (DriveTarget *dst, const DriveTarget *src))
UNREACHED(void, taicop_initialize_drive_target, (tAICop *c))
UNREACHED(int32_t, taicop_is_near_pursuit_target, (const tAICop *c))
UNREACHED(void, taicop_update_drive_target,
          (tAICop *c, const bVector2 *pos, int32_t keep))
UNREACHED(bVector2 *, tpursuithistory_velocity_at,
          (bVector2 *out, const tPursuitHistory *h, float t))
UNREACHED(void, trackedcontroller_destroy,
          (TrackedController *c, int32_t flags))
UNREACHED(void, trackedcontroller_find_where_i_am, (TrackedController *c))
UNREACHED(float, trackedcontroller_get_amount_out_of_bounds,
          (TrackedController *c))
UNREACHED(TrackRoute *, trackedcontroller_get_current_route,
          (TrackedController *c, int find))
UNREACHED(TrackRoutePoint *, trackedcontroller_get_current_route_point,
          (TrackedController *c, int find))
UNREACHED(TrackedController *, trackedcontroller_init,
          (TrackedController *c, struct Car *k))
UNREACHED(void, trackedcontroller_just_reset, (TrackedController *c))
UNREACHED(void, trackedcontroller_set_current_route,
          (TrackedController *c, TrackRoute *r, TrackRoutePoint *p))
UNREACHED(void, trackedcontroller_think, (TrackedController *c, float dt))
UNREACHED(float, trpoint_get_driving_line_speed,
          (const TrackRoutePoint *p, int line))

#undef UNREACHED

// ------------------------------------------------------------ the fields

typedef struct Group {
    const char *name;
    void       *p;
    int         n;
    char        kind;   // f a float, h a u16, w a word
} Group;

#define MAXG 24

static Group mvg[MAXG], csg[MAXG], carg[MAXG], drvg[MAXG], ctig[MAXG];
static int   nmvg, ncsg, ncarg, ndrvg, nctig;

static void add(Group *g, int *n, const char *name, void *p, int count,
                char kind)
{
    g[*n].name = name;
    g[*n].p = p;
    g[*n].n = count;
    g[*n].kind = kind;
    (*n)++;
}

static void groups(void)
{
    CarState *cs = &car.State;
    int i;
    static const char *wn[4] = { "w0", "w1", "w2", "w3" };

    add(mvg, &nmvg, "vel", &mv->v3Velocity.x, 4, 'f');
    add(mvg, &nmvg, "ta", &mv->v2TransverseAccel.x, 2, 'f');
    add(mvg, &nmvg, "face", &mv->aFacingAngle, 2, 'h');
    add(mvg, &nmvg, "spd", &mv->fSpeed, 6, 'f');
    add(mvg, &nmvg, "n68", mv->New68, 3, 'w');
    add(mvg, &nmvg, "dvel", &mv->v3DesiredVelocity.x, 4, 'f');
    add(mvg, &nmvg, "norm", &mv->v3GroundNormal.x, 3, 'f');
    add(mvg, &nmvg, "st", &mv->bIsAirborne, 2, 'w');
    add(mvg, &nmvg, "pad", mv->_pad120, 2, 'w');

    add(csg, &ncsg, "gp", &cs->GeometryPosition.x, 4, 'f');
    add(csg, &ncsg, "pos", &cs->Position.x, 4, 'f');
    add(csg, &ncsg, "vel", &cs->Velocity.x, 4, 'f');
    add(csg, &ncsg, "bm", &cs->BodyMatrix, 16, 'f');
    add(csg, &ncsg, "av", &cs->AngularVelocity.x, 3, 'f');
    add(csg, &ncsg, "wav", cs->WheelAngularVelocity, 4, 'f');
    add(csg, &ncsg, "wang", cs->WheelAngle, 4, 'f');
    add(csg, &ncsg, "wzf", cs->WheelZForce, 4, 'f');
    add(csg, &ncsg, "wbo", cs->WheelBottomOutMagnitude, 4, 'f');
    add(csg, &ncsg, "wsh", cs->WheelSuspensionHeight, 4, 'f');
    add(csg, &ncsg, "wslip", cs->WheelSlip, 8, 'f');
    add(csg, &ncsg, "wtu", cs->WheelTractionUsage, 4, 'f');
    add(csg, &ncsg, "angle", &cs->Angle, 2, 'h');
    add(csg, &ncsg, "fs", &cs->ForwardSpeed, 2, 'f');
    add(csg, &ncsg, "mv", &cs->MatrixValid, 1, 'w');

    add(carg, &ncarg, "nitro", &car.NitroEffectFlag, 1, 'w');

    add(drvg, &ndrvg, "steer", &drv.Steering, 1, 'h');
    add(drvg, &ndrvg, "thr", &drv.Throttle, 3, 'f');

    add(ctig, &nctig, "type", &cti.Type, 1, 'w');
    add(ctig, &nctig, "cog", &cti.CenterOfGravity.x, 4, 'f');
    for (i = 0; i < 4; i++)
        add(ctig, &nctig, wn[i], &cti.Wheels[i].PositionX, 4, 'f');
}

static Group *find(const char *obj, const char *name)
{
    Group *g;
    int n, i;

    if (strcmp(obj, "mv") == 0) {
        g = mvg;
        n = nmvg;
    } else if (strcmp(obj, "cs") == 0) {
        g = csg;
        n = ncsg;
    } else if (strcmp(obj, "car") == 0) {
        g = carg;
        n = ncarg;
    } else if (strcmp(obj, "drv") == 0) {
        g = drvg;
        n = ndrvg;
    } else if (strcmp(obj, "cti") == 0) {
        g = ctig;
        n = nctig;
    } else {
        fprintf(stderr, "no object %s\n", obj);
        exit(3);
    }
    for (i = 0; i < n; i++)
        if (strcmp(g[i].name, name) == 0)
            return &g[i];
    fprintf(stderr, "no group %s.%s\n", obj, name);
    exit(3);
}

static void poke(Group *g, int i, uint32_t v)
{
    if (g->kind == 'h')
        ((uint16_t *)g->p)[i] = (uint16_t)v;
    else
        memcpy((uint32_t *)g->p + i, &v, 4);
}

static void show(const char *obj, Group *g, int n)
{
    int i, k;

    for (i = 0; i < n; i++) {
        printf("  %s.%s", obj, g[i].name);
        for (k = 0; k < g[i].n; k++) {
            if (g[i].kind == 'h') {
                printf(" %d", ((uint16_t *)g[i].p)[k]);
            } else {
                uint32_t v;
                memcpy(&v, (uint32_t *)g[i].p + k, 4);
                if (g[i].kind == 'f')
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

static const VtEntry *slot(int32_t off)
{
    return vt_slot(mv->Mover._vtable, off);
}

static void op(char **a, int na)
{
    const char *o = a[0];

    if (strcmp(o, "tag") == 0) {
        printf("# %s\n", a[1]);
    } else if (strcmp(o, "set") == 0) {
        poke(find(a[1], a[2]), (int)num(a[3]), num(a[4]));
    } else if (strcmp(o, "ground") == 0) {
        ground.gz = fbits(num(a[1]));
        ground.gx = fbits(num(a[2]));
        ground.gy = fbits(num(a[3]));
        ground.sx = fbits(num(a[4]));
        ground.sz = fbits(num(a[5]));
        ground.found = (int32_t)num(a[6]);
        ground.n[0] = fbits(num(a[7]));
        ground.n[1] = fbits(num(a[8]));
        ground.n[2] = fbits(num(a[9]));
        ground.n[3] = fbits(num(a[10]));
        ground.terrain = (int32_t)num(a[11]);
        ground.sy = fbits(num(a[12]));
    } else if (strcmp(o, "lvl") == 0) {
        mgr.nDifficultyLevel = (int32_t)num(a[1]);
    } else if (strcmp(o, "new") == 0) {
        CarMover *r;
        memset(mvu.b, 0xcd, sizeof mvu.b);
        r = gCopMoverCtorFn(mvu.b, &car);
        printf("new -> %s %08x\n", lab(r), (unsigned)mv->Mover._vtable);
    } else if (strcmp(o, "move") == 0) {
        const VtEntry *e = slot(CARMOVER_VT_MOVE);
        float r = ((CarMoverMoveFn)e->fn)(vt_this(mv, e), fbits(num(a[1])));
        printf("move -> %s\n", hx(bitsf(r)));
    } else if (strcmp(o, "del") == 0) {
        const VtEntry *e = slot(CARMOVER_VT_DTOR);
        ((CarMoverDtorFn)e->fn)(vt_this(mv, e), (int32_t)num(a[1]));
        printf("del\n");
    } else if (strcmp(o, "dtor") == 0) {
        // Called directly, over another table.
        mv->Mover._vtable = num(a[2]);
        copmover_destroy(mv, (int32_t)num(a[1]));
        printf("dtor\n");
    } else if (strcmp(o, "cfa") == 0) {
        float r = copmover_calculate_facing_angle(mv, fbits(num(a[1])),
                                                  fbits(num(a[2])));
        printf("cfa -> %s %d\n", hx(bitsf(r)), mv->aFacingAngle);
    } else if (strcmp(o, "rmta") == 0) {
        copmover_reset_max_throttle_accel(mv);
        printf("rmta %s\n", hx(bitsf(mv->fMaxThrottleAccel)));
    } else if (strcmp(o, "gta") == 0) {
        printf("gta -> %s\n", lab(copmover_get_transverse_accel(mv)));
    } else if (strcmp(o, "air") == 0) {
        printf("air -> %d\n", (int)copmover_is_airborne(mv));
    } else if (strcmp(o, "smt") == 0) {
        copmover_set_max_throttle_accel(mv, fbits(num(a[1])));
    } else if (strcmp(o, "smb") == 0) {
        copmover_set_max_brake_accel(mv, fbits(num(a[1])));
    } else if (strcmp(o, "sbm") == 0) {
        copmover_set_base_max_speed(mv, fbits(num(a[1])));
    } else if (strcmp(o, "gms") == 0) {
        printf("gms -> %s\n", hx(bitsf(copmover_get_max_speed(mv))));
    } else if (strcmp(o, "sdv") == 0) {
        bVector3 v;
        v.x = fbits(num(a[1]));
        v.y = fbits(num(a[2]));
        v.z = fbits(num(a[3]));
        v.pad = fbits(num(a[4]));
        copmover_set_desired_velocity(mv, &v);
    } else if (strcmp(o, "sds") == 0) {
        copmover_set_desired_speed(mv, fbits(num(a[1])));
    } else if (strcmp(o, "sda") == 0) {
        copmover_set_desired_angle(mv, (uint16_t)num(a[1]));
    } else if (strcmp(o, "sst") == 0) {
        copmover_set_state(mv, (eCopMoverState)num(a[1]));
    } else if (strcmp(o, "dump") == 0) {
        printf("dump\n");
        show("mv", mvg, nmvg);
        show("cs", csg, ncsg);
        show("car", carg, ncarg);
        show("drv", drvg, ndrvg);
    } else {
        fprintf(stderr, "bad op %s (%d)\n", o, na);
        exit(3);
    }
}

int main(int argc, char **argv)
{
    static char line[1 << 12];
    FILE *f;

    if (argc != 2) {
        fprintf(stderr, "usage: copmover_test script.txt\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    car.pCarTypeInfo = &cti;
    car.pCarDriver = &drv;
    groups();
    vt_reset();
    copmover_install_vtables();
    copmover_install_seams();
    while (fgets(line, sizeof line, f) != NULL) {
        char *a[32], *s = line;
        int   na = 0;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        while (na < 32) {
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
