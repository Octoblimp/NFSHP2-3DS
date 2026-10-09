// Harness for tools/cop_check.py: runs the checker's script on cop.c --
// tCop, tPlayerCop and tAICop's constructors and destructors, the setters,
// ClearPursuit, ClearSpeedTrap, DisableMyCar, the zones, the drive
// target (IsNearPursuitTarget, InitializeDriveTarget, UpdateDriveTarget),
// tAICop::Think with its transitions and the limbo, disabled and guard
// logic, the radar trap's, roadblock's and patrol's logic with
// coputil.c's CanTeleport and CarCausedRecentCollision, and the chase:
// the hot pursuit and caught speeder logic, ReturnToPatrol and
// GetBestFlankSide, with coputil.c's DidTheseCarsCollide -- and on
// copmgr.c's CreateCop, 0x002276a0, AddCopCarToRace and ResetAllDamage,
// and prints what the model prints for the retail image. See the
// checker's docstring.
//
//     cop_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "airoute.h"
#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "carinit.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "collision.h"
#include "collisionbody.h"
#include "cardriver.h"
#include "configitems.h"
#include "cop.h"
#include "copdriver.h"
#include "copmgr.h"
#include "coputil.h"
#include "drivetarget.h"
#include "drivetargetrenderer.h"
#include "race.h"
#include "racecoord.h"
#include "raceparams.h"
#include "racesplit.h"
#include "realdriver.h"
#include "realtime.h"
#include "timer.h"
#include "topology.h"
#include "trackgraph.h"
#include "trackmap.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

// Retail's sizeof(Car), which its bMalloc is asked for.
#define RETAIL_CAR_SIZE 2208

#define NCARS_ 4

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

// ------------------------------------------------------------ the names

#define MAX_NAMES 1024

static struct {
    const void *p;
    char        name[24];
} names[MAX_NAMES];
static int nnames;

static void name(const void *p, const char *fmt, int k)
{
    if (nnames == MAX_NAMES) {
        fprintf(stderr, "too many names\n");
        exit(2);
    }
    names[nnames].p = p;
    snprintf(names[nnames].name, sizeof names[nnames].name, fmt, k);
    nnames++;
}

static char symbuf[8][32];
static int  symnext;

static int route_sym(const void *p, char *b);

static const char *sym(const void *p)
{
    char     *b = symbuf[symnext++ & 7];
    uintptr_t u = (uintptr_t)p;
    int       i;

    if (p == NULL)
        return "0";
    if (u == (uintptr_t)0xcdcdcdcdcdcdcdcdull)
        return "cd";
    for (i = nnames - 1; i >= 0; i--)
        if (names[i].p == p)
            return names[i].name;
    if (route_sym(p, b))
        return b;
    if (pCopManager != NULL) {
        const tSpeedTrap *t = pCopManager->SpeedTraps;
        const tSpeedTrap *q = (const tSpeedTrap *)p;

        if (q >= t && q < t + 64) {
            snprintf(b, 32, "ST%d", (int)(q - t));
            return b;
        }
    }
    return "?";
}

static void *block(size_t size)
{
    uint8_t *p = malloc(size);

    memset(p, 0xcd, size);
    return p;
}

// -------------------------------------------- what cop.c and copmgr.c reach

RaceParameters   TheRaceParameters;
World           *pCurrentWorld;
float            SkipFETimeUntilCopsAppear;

// copmgr.c's Think reaches these; nothing here runs it. tAICop::Think
// reads WorldTimeElapsed.
float            WorldTimeElapsed;
Race            *pCurrentRace;
RaceCoordinator *pRaceCoordinator;
tTrackGraph     *TheTrackGraph;

// tAICop::Think's: the camera's car, and the renderer it hands the car's
// target to.
int32_t             CameraFollowThisCarInstead = -1;
DriveTargetRenderer TheDriveTargetRenderer;

// What World's distance to the nearest player answers, from the script:
// the queue's answers first, in order, then dist_answer.
static float dist_answer;
static float distq[16];
static int   ndistq, distq_at;

void trackgraph_uncloak_all_edges(tTrackGraph *g)
{
    (void)g;
    abort();
}

float world_get_distance_to_closest_player_2d(const World *w,
                                              const bVector2 *pos)
{
    float r = distq_at < ndistq ? distq[distq_at++] : dist_answer;

    printf("  dist %s %08x %08x -> %08x\n", sym(w), fb(pos->x), fb(pos->y),
           fb(r));
    return r;
}

void drivetargetrenderer_set_target_to_render(DriveTargetRenderer *r,
                                              DriveTarget *t)
{
    printf("  render %s", sym(r));
    printf(" %s\n", sym(t));
}

void collisionbody_enable_collisions(CollisionBody *b)
{
    printf("  collon %s\n", sym(b));
}

void collisionbody_disable_collisions(CollisionBody *b)
{
    printf("  colloff %s\n", sym(b));
}

void realdriver_force_ebrake_stop(RealDriver *d, float t)
{
    printf("  ebrake %s %08x\n", sym(d), fb(t));
}

#define NCARS NCARS_

static World       world;
static Car         cars[NCARS];
static CarTypeInfo types[4];
static DriverInfo  dinfo[4];
static tPursuit    pursuits[5];
static uint8_t     player_token[16], dmg_token[16], pool_token[16];
static int         info_type[5];               // by DriverInfo, NULL first
static int         nm, no, nk, nr;
static int         respk = -2;
static tCop       *disabling;

// The drive target's world: three routes of real points, each car's
// driver, and the rules the route stand-ins answer by.
#define NQ    3
#define QPTS  40
static TrackRoute qroutes[NQ];
static int        qcount[NQ], qlink[NQ];
static CarDriver  drivers[NCARS];
static int        car_q[NCARS], car_i[NCARS];
static int        nearq[16][3], nnear, near_at;
static bVector2   dtpos;

static void *kinds_p[MAX_NAMES];

// A route point's name, Q<route>.p<point>, into b.
static int route_sym(const void *p, char *b)
{
    int i;

    for (i = 0; i < NQ; i++) {
        const uint8_t *t = (const uint8_t *)qroutes[i].TrackRoutePointTable;
        const uint8_t *q = (const uint8_t *)p;

        if (q >= t && q < t + QPTS * 112 && (q - t) % 112 == 0) {
            snprintf(b, 32, "Q%d.p%d", i, (int)((q - t) / 112));
            return 1;
        }
    }
    return 0;
}

static char  kinds_k[MAX_NAMES][8];
static int   nkinds;

static void unreached(const char *f)
{
    fprintf(stderr, "cop_test: %s reached\n", f);
    exit(3);
}

int32_t config_skip_fe(void) { unreached("config_skip_fe"); return 0; }

void *bMalloc(int size, const char *nm_, int flags, int pool)
{
    void *p = block((size_t)size);

    name(p, "M%d", nm);
    if (!strcmp(nm_, "tPlayerCop"))
        printf("  malloc2 52 %d -> M%d\n", pool, nm);
    else
        printf("  malloc %d %s %d %d -> M%d\n",
               size == (int)sizeof(Car) ? RETAIL_CAR_SIZE : size, nm_, flags,
               pool, nm);
    nm++;
    return p;
}

void bFree(void *p)
{
    printf("  delete %s\n", sym(p));
}

void *bSlotOMalloc(BSlotPool *pool)
{
    void *p = block(256);

    name(p, "O%d", no);
    printf("  omalloc %s -> O%d\n", sym(pool), no);
    no++;
    return p;
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    printf("  sfree %s", sym(pool));
    printf(" %s\n", sym(slot));
}

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *nm_,
                        int memoryPool)
{
    (void)slotSize; (void)numSlots; (void)nm_; (void)memoryPool;
    unreached("bNewSlotPool");
    return NULL;
}

void bDeleteSlotPool(BSlotPool *pool)
{
    (void)pool;
    unreached("bDeleteSlotPool");
}

static TrackRoutePoint *qpoint(int q, int i)
{
    if (q < 0 || i < 0)
        return NULL;
    return &qroutes[q].TrackRoutePointTable[i];
}

// The next answer from the script's queue -- the last again once it runs
// out, and 0 with info untouched when it is empty: the return, and the
// route and point it leaves (q -1 both NULL, -2 untouched).
int ai_get_nearest_route_point(NearestRoutePointInfo *info,
                               const bVector2 *pos, RoutesToSearch which,
                               int flags, float distanceAround)
{
    int r = 0;

    printf("  nearest %08x %08x %d %d %08x", fb(pos->x), fb(pos->y),
           (int)which, flags, fb(distanceAround));
    if (nnear > 0) {
        const int *a = nearq[near_at < nnear ? near_at : nnear - 1];

        near_at++;
        r = a[0];
        if (a[1] == -1) {
            info->Route = NULL;
            info->Point = NULL;
        } else if (a[1] >= 0) {
            info->Route = &qroutes[a[1]];
            info->Point = qpoint(a[1], a[2]);
        }
    }
    printf(" -> %d %s", r, sym(info->Route));
    printf(" %s\n", sym(info->Point));
    return r;
}

// One point on, along the route; off its end to point 0 of the route it
// links to, or to a NULL point.
void ai_get_next_route_point(NearestRoutePointInfo *info)
{
    int q, i = -1;

    printf("  next %s", sym(info->Route));
    printf(" %s", sym(info->Point));
    for (q = 0; q < NQ; q++)
        if (info->Route == &qroutes[q])
            break;
    if (q < NQ && info->Point != NULL) {
        const uint8_t *t = (const uint8_t *)qroutes[q].TrackRoutePointTable;
        const uint8_t *u = (const uint8_t *)info->Point;

        if (u >= t && u < t + QPTS * 112 && (u - t) % 112 == 0)
            i = (int)((u - t) / 112);
    }
    if (q == NQ || i < 0) {
        info->Point = NULL;
    } else if (i + 1 < qcount[q]) {
        info->Point = qpoint(q, i + 1);
    } else if (qlink[q] >= 0) {
        info->Route = &qroutes[qlink[q]];
        info->Point = qpoint(qlink[q], 0);
    } else {
        info->Point = NULL;
    }
    printf(" -> %s", sym(info->Route));
    printf(" %s\n", sym(info->Point));
}

static int car_k(const Car *c)
{
    int k;

    for (k = 0; k < NCARS; k++)
        if (c == &cars[k])
            return k;
    return -1;
}

TrackRoute *car_get_route(Car *c, int find)
{
    int k = car_k(c);
    TrackRoute *r = k >= 0 && car_q[k] >= 0 ? &qroutes[car_q[k]] : NULL;

    printf("  getroute %s %d -> %s\n", sym(c), find, sym(r));
    return r;
}

TrackRoutePoint *car_get_route_point(Car *c, int find)
{
    int k = car_k(c);
    TrackRoutePoint *p = k >= 0 ? qpoint(car_q[k], car_i[k]) : NULL;

    printf("  getrp %s %d -> %s\n", sym(c), find, sym(p));
    return p;
}

void drivetarget_clear(DriveTarget *t, Car *car, float speed)
{
    printf("  dtclear %s", sym(t));
    printf(" %s %08x\n", sym(car), fb(speed));
}

void drivetarget_add_point3(DriveTarget *t, const bVector3 *p, int8_t route,
                            int16_t rpn, int8_t dl, int check, Car *car)
{
    printf("  addpt %s %08x %08x %08x %d %d %d %d", sym(t), fb(p->x),
           fb(p->y), fb(p->z), route, rpn, dl, check);
    printf(" %s\n", sym(car));
}

void topology_init(TopologyCoordinate *tc)
{
    (void)tc;
    unreached("topology_init");
}

int topology_has_topology(TopologyCoordinate *tc, const bVector2 *xy)
{
    (void)tc; (void)xy;
    unreached("topology_has_topology");
    return 0;
}

void topology_destroy(TopologyCoordinate *tc)
{
    (void)tc;
    unreached("topology_destroy");
}

// World::Random's answers and CarState::WorldToCar's, from the script,
// each queue in turn and round again (0 for an empty one).
static int32_t  randi_q[16];
static uint32_t randf_q[16], w2c_q[16][2];
static int      nrandi, randi_at, nrandf, randf_at, nw2c, w2c_at;

int32_t world_random_i(World *w, int32_t range)
{
    int32_t r = nrandi ? randi_q[randi_at++ % nrandi] : 0;

    printf("  randi %s %d -> %d\n", sym(w), range, r);
    return r;
}

float world_random_f(World *w, float f)
{
    uint32_t r = nrandf ? randf_q[randf_at++ % nrandf] : 0;

    printf("  randf %s %08x -> %08x\n", sym(w), fb(f), r);
    return bf(r);
}

void carstate_world_to_car2(CarState *s, bVector2 *out, const bVector2 *in)
{
    const uint32_t *r = w2c_q[nw2c ? w2c_at++ % nw2c : 0];
    int             k;

    for (k = 0; k < NCARS; k++)
        if (s == &cars[k].State)
            break;
    out->x = bf(nw2c ? r[0] : 0);
    out->y = bf(nw2c ? r[1] : 0);
    printf("  w2c A%d %08x %08x -> %08x %08x\n", k, fb(in->x), fb(in->y),
           fb(out->x), fb(out->y));
}

int32_t is_point_in_poly(const bVector2 *p, const bVector2 *poly, int32_t n)
{
    (void)p; (void)poly; (void)n;
    unreached("is_point_in_poly");
    return 0;
}

// The manager's SpawnSpeedTraps (12j-1), which copmanager_check checks.
void race_calculate_split_time(Race *r, Timer *out, struct RacingCar *a,
                               struct RacingCar *b)
{
    (void)r; (void)out; (void)a; (void)b;
    unreached("race_calculate_split_time");
}

int32_t race_parameters_is_free_run(const RaceParameters *rp)
{
    (void)rp;
    unreached("race_parameters_is_free_run");
    return 0;
}

void timer_set_time(Timer *t, float seconds)
{
    (void)t; (void)seconds;
    unreached("timer_set_time");
}

struct tSpeedTrap *trackgraph_find_speed_trap(tTrackGraph *g,
                                              struct Car *car, float fMin,
                                              float fMax, int32_t forward)
{
    (void)g; (void)car; (void)fMin; (void)fMax; (void)forward;
    unreached("trackgraph_find_speed_trap");
    return NULL;
}

// CarCausedRecentCollision's world: each car's collisions, as the script
// sets them -- whether two cars, and the two cars by number (-1 none) --
// and Car::IsCarInFront's answers, by car and other car.
#define NCOLS 8
static int     coll_n[NCARS_], coll_two[NCARS_][NCOLS];
static int     coll_a[NCARS_][NCOLS], coll_b[NCARS_][NCOLS];
static uint8_t coltok[NCARS_][NCOLS][16];
static int     front[NCARS_][NCARS_];

static Car *car_or_null(int k);

static int col_ji(const Collision *c, int *j, int *i)
{
    for (*j = 0; *j < NCARS_; (*j)++)
        for (*i = 0; *i < NCOLS; (*i)++)
            if ((const void *)coltok[*j][*i] == (const void *)c)
                return 1;
    abort();
}

struct Collision *collisionbody_get_collision(CollisionBody *b, int32_t i)
{
    Collision *r = NULL;
    int        j;

    for (j = 0; j < NCARS_; j++)
        if ((void *)car_or_null(j)->pDynamicCollisionBody == (void *)b
            && 0 <= i && i < NCOLS)
            r = (Collision *)(void *)coltok[j][i];
    printf("  getcol %s %d", sym(b), i);
    printf(" -> %s\n", sym(r));
    return r;
}

int32_t collision_is_two_car_collision(Collision *c)
{
    int j, i, two;

    col_ji(c, &j, &i);
    two = i < coll_n[j] ? coll_two[j][i] : 0;
    printf("  twocar %s -> %d\n", sym(c), two);
    return two;
}

void collision_get_colliding_cars(Collision *c, Car **car1, Car **car2)
{
    int j, i, a = -1, b = -1;

    col_ji(c, &j, &i);
    if (i < coll_n[j]) {
        a = coll_a[j][i];
        b = coll_b[j][i];
    }
    *car1 = car_or_null(a);
    *car2 = car_or_null(b);
    printf("  cars %s", sym(c));
    printf(" -> %s", sym(*car1));
    printf(" %s\n", sym(*car2));
}

int32_t car_is_car_in_front(Car *c, Car *other, uint16_t angle)
{
    int j = car_k(c), k = car_k(other);
    int r = j >= 0 && k >= 0 ? front[j][k] : 0;

    printf("  infront %s", sym(c));
    printf(" %s %d -> %d\n", sym(other), angle, r);
    return r;
}

Car *car_construct(Car *c, DriverInfo *driver, const bVector3 *pos,
                   uint16_t angle, float dist)
{
    int k;

    printf("  carctor %s", sym(c));
    printf(" %s pos %08x %08x %08x ang %d dist %08x\n", sym(driver),
           fb(pos->x), fb(pos->y), fb(pos->z), angle, fb(dist));
    k = driver == NULL ? info_type[0] : info_type[1 + (driver - dinfo)];
    c->pCarTypeInfo = &types[k];
    c->State.Position.x = pos->x;
    c->State.Position.y = pos->y;
    return c;
}

void car_set_control_mode(Car *c, ControlMode mode)
{
    CopDriver *d = block(sizeof(CopDriver));

    name(d, "K%d", nk);
    c->TheControlMode = mode;
    c->pCarController = (CarController *)(void *)d;
    printf("  ctrlmode %s %d -> K%d\n", sym(c), (int)mode, nk);
    nk++;
}

void car_set_movement_mode(Car *c, MovementMode mode)
{
    c->TheMovementMode = mode;
    printf("  movemode %s %d\n", sym(c), (int)mode);
}

void car_reset_to_position(Car *c, const bVector3 *pos, float speed,
                           uint16_t angle)
{
    printf("  reset %s pos %08x %08x %08x speed %08x ang %d\n", sym(c),
           fb(pos->x), fb(pos->y), fb(pos->z), fb(speed), angle);
}

static void rmcop(tPursuit *p, tCop *c)
{
    printf("  rmcop %s", sym(p));
    printf(" %s\n", sym(c));
}

static void rmspk(tPursuit *p, int32_t b)
{
    printf("  rmspk %s %d\n", sym(p), b);
    if (respk != -2)
        disabling->pMyPursuit = respk >= 0 ? &pursuits[respk] : NULL;
}

static void wreck(void *damage)
{
    printf("  wreck %s\n", sym(damage));
}

static void repair(void *damage)
{
    printf("  repair %s\n", sym(damage));
}

static uint32_t reqp_answer;

// A pursuit granted is U4's, chasing the car, with the cop its primary.
static int32_t reqp(tCopManager *mm, tCop *c, Car *car)
{
    printf("  reqp %s", sym(mm));
    printf(" %s", sym(c));
    printf(" %s -> %d\n", sym(car), (int32_t)reqp_answer);
    if (reqp_answer) {
        pursuits[4].pChasedCar = car;
        pursuits[4].Cops[0] = c;
        pursuits[4].Cops[1] = NULL;
        c->pMyPursuit = &pursuits[4];
    }
    return (int32_t)reqp_answer;
}

// The chased car's collision body's table: SetToPhysicsMode and
// ApplyImpulse, logged.
#define CB_VT 0x00fe0000u

static VtEntry cb_vt[COLLISIONBODY_VT_ENTRIES];

static void cb_physmode(void *self, CollisionBody *other)
{
    printf("  physmode %s", sym(self));
    printf(" %s\n", sym(other));
}

static void cb_impulse(void *self, bVector3 *j, bVector3 *at)
{
    printf("  impulse %s %08x %08x %08x %08x at %08x %08x %08x\n", sym(self),
           fb(j->x), fb(j->y), fb(j->z), fb(j->pad), fb(at->x), fb(at->y),
           fb(at->z));
}

static Car *car_or_null(int k)
{
    return k >= 0 ? &cars[k] : NULL;
}

static void pthink(tPlayerCop *c)
{
    printf("  pthink %s\n", sym(c));
}

// The NullDriver's table, for the cars' drivers: SetDesiredSpeed, logged.
static void nd_speed(void *self, float speed, float time, float tol,
                     int32_t allowed)
{
    printf("  ndspeed %s %08x %08x %08x %d\n", sym(self), fb(speed), fb(time),
           fb(tol), allowed);
}

static VtEntry nd_vt[CARDRIVER_VT_ENTRIES];

// ---------------------------------------------------------- the dump

// Python's " ".join: nothing for none.
static void sep(int i)
{
    if (i)
        printf(" ");
}

static uint32_t word(const void *p)
{
    uint32_t w;

    memcpy(&w, p, 4);
    return w;
}

static const char *kind(tCop *c)
{
    int i;

    for (i = 0; i < nkinds; i++)
        if (kinds_p[i] == c)
            return kinds_k[i];
    kinds_p[nkinds] = c;
    strcpy(kinds_k[nkinds],
           c->vptr == TCOP_VTABLE ? "tcop"
           : c->vptr == TPLAYERCOP_VTABLE ? "player"
           : c->vptr == TAICOP_VTABLE ? "ai" : "?");
    return kinds_k[nkinds++];
}

static void dump_car(int k, Car *car)
{
    printf("C%d car type %s", k, sym(car->pCarTypeInfo));
    printf(" next %s", sym(car->Link.next));
    printf(" prev %s render %02x lights %08x siren %08x vis %08x",
           sym(car->Link.prev), (uint8_t)car->RenderingEnabled,
           word(&car->CopLights), (uint32_t)car->TheSirenMode,
           (uint32_t)car->bVisibleOnTrackMap);
    printf(" dmg %s mode %08x move %08x pos %08x %08x", sym(car->pCarDamage),
           (uint32_t)car->TheControlMode, (uint32_t)car->TheMovementMode,
           fb(car->State.Position.x), fb(car->State.Position.y));
    printf(" ctrl %s\n", sym(car->pCarController));
    if (car->pCarController != NULL
        && (uintptr_t)car->pCarController
           != (uintptr_t)0xcdcdcdcdcdcdcdcdull) {
        const CopDriver *d = (const CopDriver *)(void *)car->pCarController;

        printf("C%d drv %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x\n",
               k, (uint32_t)d->State, (uint32_t)d->StateBeforeGettingStuck,
               (uint32_t)d->SubState, fb(d->fStuckTimer),
               fb(d->fBackingUpTimer), fb(d->fPatrolSpeed),
               (uint32_t)d->nCopIndex, fb(d->v2SteerTarget.x),
               fb(d->v2SteerTarget.y), (uint32_t)d->nCarClass);
    }
}

static int is_world_car(const Car *c)
{
    int i;

    for (i = 0; i < NCARS; i++)
        if (c == &cars[i])
            return 1;
    return 0;
}

static void dump_cop(int k, tCop *c)
{
    const char *kd = kind(c);

    printf("C%d %s %s vt %08x", k, sym(c), kd, c->vptr);
    printf(" pu %s", sym(c->pMyPursuit));
    printf(" car %s n %d ls %08x %08x lss %08x %08x\n", sym(c->pMyCar),
           c->nCopNumber, (uint32_t)c->LogicState,
           (uint32_t)c->DesiredLogicState, (uint32_t)c->LogicSubState,
           (uint32_t)c->DesiredLogicSubState);
    if (!strcmp(kd, "ai")) {
        tAICop *a = (tAICop *)(void *)c;

        printf("C%d ai %08x st %s rb %08x sst %08x %08x %08x dl %08x %08x "
               "%08x %08x flank %08x", k, fb(a->New32), sym(a->pMySpeedTrap),
               (uint32_t)a->nMyRoadBlockIndex, fb(a->fSubStateTimer),
               fb(a->New48.x), fb(a->New48.y), fb(a->MyDLOffset.x),
               fb(a->MyDLOffset.y), fb(a->New64), fb(a->New68),
               fb(a->fFlankSide));
        printf(" route %s", sym(a->RouteInfo.Route));
        printf(" %s phys %08x delay %08x line %08x\n",
               sym(a->RouteInfo.Point), fb(a->fSecondsInPhysicsMode),
               fb(a->fMovementModeSwitchDelay),
               (uint32_t)a->nDrivingLineIndex);
    } else if (!strcmp(kd, "player")) {
        tPlayerCop *p = (tPlayerCop *)(void *)c;

        printf("C%d pl %08x %08x %08x %08x %08x\n", k,
               (uint32_t)p->nPrevSelection[0], (uint32_t)p->nPrevSelection[1],
               fb(p->fPrevSelectionTimer[0]), fb(p->fPrevSelectionTimer[1]),
               (uint32_t)p->bPrevCopLightState);
    }
    if (c->pMyCar != NULL
        && (uintptr_t)c->pMyCar != (uintptr_t)0xcdcdcdcdcdcdcdcdull
        && !is_world_car(c->pMyCar))
        dump_car(k, c->pMyCar);
}

static void dump(void)
{
    tCopManager *m = pCopManager;
    const void  *n;
    int          k, i;

    printf("M ai %d n %d pidx %d max %08x %08x\n", m->nNumAICops,
           m->nNumCops, m->nPlayerCopIndex, fb(m->fMaxCopCarXdim),
           fb(m->fMaxCopCarYdim));
    printf("M cops");
    for (k = 0; k < 7; k++)
        printf(" %s", sym(m->Cops[k]));
    printf("\nM timers");
    for (k = 0; k < 8; k++)
        printf(" %08x", fb(m->fSpeedTrapSpawnTimer[k]));
    printf(" dmg");
    for (k = 0; k < 2; k++)
        printf(" %08x", fb(m->fCarDamage[k]));
    printf("\nM traps ");
    for (k = 0; k < m->nNumSpeedTraps; k++) {
        sep(k);
        printf("%s", sym(m->SpeedTraps[k].cop));
    }
    printf("\nW ");
    for (i = 0, n = world.CarList.next; n != (void *)&world && i < 24; i++) {
        sep(i);
        printf("%s", sym(n));
        n = ((const CarNode *)n)->next;
    }
    printf(" | ");
    for (i = 0, n = world.CarList.prev; n != (void *)&world && i < 24; i++) {
        sep(i);
        printf("%s", sym(n));
        n = ((const CarNode *)n)->prev;
    }
    printf("\n");
    for (k = 0; k < 4; k++) {
        const RigidBodyInfo *b = &types[k].Body;
        const bVector4      *r[4] = { &b->InertiaTensor.v0,
                                      &b->InertiaTensor.v1,
                                      &b->InertiaTensor.v2,
                                      &b->InertiaTensor.v3 };

        printf("T%d %08x %08x %08x %08x", k, fb(b->Mass), fb(b->Xdim),
               fb(b->Ydim), fb(b->Zdim));
        for (i = 0; i < 4; i++)
            printf(" %08x %08x %08x %08x", fb(r[i]->x), fb(r[i]->y),
                   fb(r[i]->z), fb(r[i]->w));
        printf("\n");
    }
    for (k = 0; k < 7; k++)
        if (m->Cops[k] != NULL)
            dump_cop(k, m->Cops[k]);
}

// What tAICop::Think touches: the cop, its car and the car's driver.
static void tdump(int k)
{
    tAICop    *a = (tAICop *)(void *)pCopManager->Cops[k];
    Car       *car = a->Base.pMyCar;
    CarDriver *d;

    printf("T%d cop ls %08x %08x lss %08x %08x n32 %08x sst %08x n48 %08x "
           "%08x n64 %08x %08x phys %08x delay %08x pu %s",
           k, (uint32_t)a->Base.LogicState, (uint32_t)a->Base.DesiredLogicState,
           (uint32_t)a->Base.LogicSubState,
           (uint32_t)a->Base.DesiredLogicSubState, fb(a->New32),
           fb(a->fSubStateTimer), fb(a->New48.x), fb(a->New48.y),
           fb(a->New64), fb(a->New68), fb(a->fSecondsInPhysicsMode),
           fb(a->fMovementModeSwitchDelay), sym(a->Base.pMyPursuit));
    printf(" st %s rbi %08x dl %08x %08x flank %08x line %08x\n",
           sym(a->pMySpeedTrap), (uint32_t)a->nMyRoadBlockIndex,
           fb(a->MyDLOffset.x), fb(a->MyDLOffset.y), fb(a->fFlankSide),
           (uint32_t)a->nDrivingLineIndex);
    printf("T%d car render %02x lights %08x siren %08x vis %08x move %08x "
           "vel %08x %08x %08x vmag %08x mv %08x blown %02x %02x rumble %08x "
           "trac %08x cdmg %08x\n",
           k, (uint8_t)car->RenderingEnabled, word(&car->CopLights),
           (uint32_t)car->TheSirenMode, (uint32_t)car->bVisibleOnTrackMap,
           (uint32_t)car->TheMovementMode, fb(car->State.Velocity.x),
           fb(car->State.Velocity.y), fb(car->State.Velocity.z),
           fb(car->State.VelocityMagnitude), (uint32_t)car->State.MatrixValid,
           car->BlownTireBits, car->NumBlownTires,
           fb(car->fBlownTireControllerRumbleTimer),
           fb(car->fTractionBoostOverride),
           fb(pCopManager->fCarDamage[car->CarIndex]));
    d = car->pCarDriver;
    printf("T%d drv steer %04x thr %08x brk %08x eb %08x dg %08x sg %08x "
           "ctl %08x", k, d->Steering, fb(d->Throttle), fb(d->Brake),
           fb(d->EBrake), (uint32_t)d->DesiredGear, (uint32_t)d->SportGear,
           (uint32_t)((CopDriver *)(void *)car->pCarController)->State);
    printf(" ri %s", sym(a->RouteInfo.Route));
    printf(" %s n %02x pt0 %08x %08x\n", sym(a->RouteInfo.Point),
           (uint8_t)d->MyDriveTarget.NumPoints,
           fb(d->MyDriveTarget.Points[0].x), fb(d->MyDriveTarget.Points[0].y));
}

// A field of a world car, by name: v is a float's bits, or the value.
static void car_field(Car *c, const char *f, uint32_t v)
{
    float x = bf(v);
    int   i;

    if (!strcmp(f, "upz"))
        c->State.BodyMatrix.v2.z = x;
    else if (!strcmp(f, "vmag"))
        c->State.VelocityMagnitude = x;
    else if (!strcmp(f, "fwd"))
        c->State.ForwardSpeed = x;
    else if (!strcmp(f, "vx"))
        c->State.Velocity.x = x;
    else if (!strcmp(f, "vy"))
        c->State.Velocity.y = x;
    else if (!strcmp(f, "vz"))
        c->State.Velocity.z = x;
    else if (!strcmp(f, "wx"))
        c->State.AngularVelocity.x = x;
    else if (!strcmp(f, "wy"))
        c->State.AngularVelocity.y = x;
    else if (!strcmp(f, "wz"))
        c->State.AngularVelocity.z = x;
    else if (!strcmp(f, "ang"))
        c->State.Angle = (uint16_t)v;
    else if (!strcmp(f, "wheels"))
        for (i = 0; i < 4; i++)
            c->State.WheelTouchingGround[i] = (int8_t)(v >> (8 * i));
    else if (!strcmp(f, "blown"))
        c->BlownTireBits = (uint8_t)v;
    else if (!strcmp(f, "nblown"))
        c->NumBlownTires = (uint8_t)v;
    else if (!strcmp(f, "rumble"))
        c->fBlownTireControllerRumbleTimer = x;
    else if (!strcmp(f, "trac"))
        c->fTractionBoostOverride = x;
    else if (!strcmp(f, "move"))
        c->TheMovementMode = (MovementMode)v;
    else if (!strcmp(f, "mode"))
        c->TheControlMode = (ControlMode)v;
    else if (!strcmp(f, "drvnum"))
        c->DriverNumber = (int16_t)v;
    else if (!strcmp(f, "idx"))
        c->CarIndex = (int16_t)v;
    else if (!strcmp(f, "mv"))
        c->State.MatrixValid = (int32_t)v;
    else if (!strcmp(f, "air"))
        ((CopMover *)(void *)c->pCarMover)->bIsAirborne = (int32_t)v;
    else if (!strcmp(f, "render"))
        c->RenderingEnabled = (int8_t)v;
    else if (!strcmp(f, "lights"))
        memcpy(&c->CopLights, &v, 4);
    else if (!strcmp(f, "siren"))
        c->TheSirenMode = (SirenMode)v;
    else if (!strcmp(f, "vis"))
        c->bVisibleOnTrackMap = (int32_t)v;
    else if (!strcmp(f, "dmg"))
        c->pCarDamage = v ? (CarDamage *)(void *)dmg_token : NULL;
    else if (!strcmp(f, "z"))
        c->State.Position.z = x;
    else if (!strcmp(f, "dat"))
        c->TheTrackPathCoordinate.DistanceAroundTrack = x;
    else {
        fprintf(stderr, "unknown car field %s\n", f);
        exit(2);
    }
}

static void driver_field(CarDriver *d, const char *f, uint32_t v)
{
    if (!strcmp(f, "steer"))
        d->Steering = (uint16_t)v;
    else if (!strcmp(f, "thr"))
        d->Throttle = bf(v);
    else if (!strcmp(f, "brk"))
        d->Brake = bf(v);
    else if (!strcmp(f, "eb"))
        d->EBrake = bf(v);
    else if (!strcmp(f, "dg"))
        d->DesiredGear = (Gear)v;
    else if (!strcmp(f, "sg"))
        d->SportGear = (Gear)v;
    else {
        fprintf(stderr, "unknown driver field %s\n", f);
        exit(2);
    }
}

static void cop_field(tAICop *c, const char *f, uint32_t v)
{
    float x = bf(v);

    if (!strcmp(f, "n32"))
        c->New32 = x;
    else if (!strcmp(f, "sst"))
        c->fSubStateTimer = x;
    else if (!strcmp(f, "phys"))
        c->fSecondsInPhysicsMode = x;
    else if (!strcmp(f, "delay"))
        c->fMovementModeSwitchDelay = x;
    else if (!strcmp(f, "n48x"))
        c->New48.x = x;
    else if (!strcmp(f, "n48y"))
        c->New48.y = x;
    else if (!strcmp(f, "dlx"))
        c->MyDLOffset.x = x;
    else if (!strcmp(f, "dly"))
        c->MyDLOffset.y = x;
    else if (!strcmp(f, "n64"))
        c->New64 = x;
    else if (!strcmp(f, "n68"))
        c->New68 = x;
    else if (!strcmp(f, "ls"))
        c->Base.LogicState = (eLogicState)v;
    else if (!strcmp(f, "ds"))
        c->Base.DesiredLogicState = (eLogicState)v;
    else if (!strcmp(f, "lss"))
        c->Base.LogicSubState = (eLogicSubState)v;
    else if (!strcmp(f, "dlss"))
        c->Base.DesiredLogicSubState = (eLogicSubState)v;
    else if (!strcmp(f, "rbi"))
        c->nMyRoadBlockIndex = (int32_t)v;
    else if (!strcmp(f, "flank"))
        c->fFlankSide = x;
    else if (!strcmp(f, "line"))
        c->nDrivingLineIndex = (int32_t)v;
    else {
        fprintf(stderr, "unknown cop field %s\n", f);
        exit(2);
    }
}

// ---------------------------------------------------------- the ops

static uint32_t num(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static uint32_t hex(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 16);
}

static DriverInfo *info(const char *s)
{
    int k = atoi(s);

    return k >= 0 ? &dinfo[k] : NULL;
}

static const VtEntry *slot(tCop *c, int off)
{
    return vt_slot(c->vptr, off);
}

static void op(char **a, int na)
{
    const char  *o = a[0];
    tCopManager *m = pCopManager;

    (void)na;
    if (!strcmp(o, "type")) {
        RigidBodyInfo *b = &types[atoi(a[1])].Body;
        bVector4      *r[4] = { &b->InertiaTensor.v0, &b->InertiaTensor.v1,
                                &b->InertiaTensor.v2, &b->InertiaTensor.v3 };
        int            j;

        b->Mass = bf(hex(a[2]));
        b->Xdim = bf(hex(a[3]));
        b->Ydim = bf(hex(a[4]));
        b->Zdim = bf(hex(a[5]));
        for (j = 0; j < 4; j++) {
            r[j]->x = bf(hex(a[6 + 4 * j]));
            r[j]->y = bf(hex(a[7 + 4 * j]));
            r[j]->z = bf(hex(a[8 + 4 * j]));
            r[j]->w = bf(hex(a[9 + 4 * j]));
        }
    } else if (!strcmp(o, "info")) {
        info_type[1 + atoi(a[1])] = atoi(a[2]);
    } else if (!strcmp(o, "rp")) {
        if (!strcmp(a[1], "dir"))
            TheRaceParameters.TrackDirection = (int32_t)num(a[2]);
        else if (!strcmp(a[1], "cs"))
            TheRaceParameters.CopStrength = (int32_t)num(a[2]);
        else
            TheRaceParameters.nMaxCops = (int32_t)num(a[2]);
    } else if (!strcmp(o, "world")) {
        int j;

        world.CarList.next = world.CarList.prev = &world;
        for (j = 0; j < WORLD_MAX_CARS; j++)
            world.CarTable[j] = NULL;
        for (j = 0; j < atoi(a[1]); j++) {
            Car     *c = &cars[j];
            CarNode *tail = world.CarList.prev;

            tail->next = &c->Link;
            world.CarList.prev = c;
            c->Link.prev = tail;
            c->Link.next = (CarNode *)(void *)&world;
            world.CarTable[j] = c;
        }
    } else if (!strcmp(o, "wcar")) {
        Car *c = &cars[atoi(a[1])];

        c->CarIndex = (int16_t)atoi(a[2]);
        c->State.Position.x = bf(hex(a[3]));
        c->State.Position.y = bf(hex(a[4]));
        c->pPlayer = atoi(a[5]) ? (Player *)(void *)player_token : NULL;
        c->pCarTypeInfo = &types[atoi(a[6])];
    } else if (!strcmp(o, "mgr")) {
        int j;

        m = block(sizeof *m);
        name(m, "MG", 0);
        m->nNumAICops = 0;
        m->nNumCops = 0;
        m->nPlayerCopIndex = -1;
        for (j = 0; j < 7; j++)
            m->Cops[j] = NULL;
        m->nNumSpeedTraps = 0;
        for (j = 0; j < 8; j++)
            m->fSpeedTrapSpawnTimer[j] = 0.0f;
        for (j = 0; j < 14; j++)
            m->fCarDamage[j] = 0.0f;
        m->nDifficultyLevel = (int32_t)num(a[1]);
        m->fMaxCopCarXdim = 0.0f;
        m->fMaxCopCarYdim = 0.0f;
        // The pursuit list empty, no pullovers, no pursuable timers.
        m->PursuitList.Next = m->PursuitList.Prev = &m->PursuitList;
        for (j = 0; j < 8; j++) {
            m->CarPullovers[j].bActive = 0;
            m->fPursuableTimer[j] = 0.0f;
        }
        pCopManager = m;
    } else if (!strcmp(o, "ntraps")) {
        m->nNumSpeedTraps = (int32_t)num(a[1]);
    } else if (!strcmp(o, "trap")) {
        tSpeedTrap *t = &m->SpeedTraps[atoi(a[1])];

        t->cop = NULL;
        t->v2Position.x = bf(hex(a[2]));
        t->v2Position.y = bf(hex(a[3]));
        t->ang = (uint16_t)atoi(a[4]);
        t->Flags = num(a[5]);
    } else if (!strcmp(o, "add")) {
        copmgr_add_cop_car_to_race(info(a[1]), (int32_t)num(a[2]));
        printf("add %s %d\n", a[1], (int32_t)num(a[2]));
    } else if (!strcmp(o, "create")) {
        copmanager_create_cop(m, info(a[1]), (int32_t)num(a[2]));
        printf("create %s %d\n", a[1], (int32_t)num(a[2]));
    } else if (!strcmp(o, "maxdim")) {
        copmanager_calculate_max_cop_car_dimensions(m);
        printf("maxdim\n");
    } else if (!strcmp(o, "dump")) {
        dump();
    } else if (!strcmp(o, "isai")) {
        tCop          *c = m->Cops[atoi(a[1])];
        const VtEntry *e = slot(c, TCOP_VT_IS_AI_CONTROLLED);

        printf("isai %s -> %d\n", a[1],
               ((int32_t (*)(void *))e->fn)(vt_this(c, e)));
    } else if (!strcmp(o, "dtor")) {
        tCop          *c = m->Cops[atoi(a[1])];
        const VtEntry *e = slot(c, TCOP_VT_DTOR);

        ((void (*)(void *, int32_t))e->fn)(vt_this(c, e), (int32_t)num(a[2]));
        printf("dtor %s %d\n", a[1], (int32_t)num(a[2]));
    } else if (!strcmp(o, "setp") || !strcmp(o, "setds")
               || !strcmp(o, "setdss")) {
        tCop *c = m->Cops[atoi(a[1])];

        if (!strcmp(o, "setp")) {
            int k = atoi(a[2]);

            tcop_set_pursuit(c, k >= 0 ? &pursuits[k] : NULL);
        } else if (!strcmp(o, "setds")) {
            tcop_set_desired_logic_state(c, (eLogicState)num(a[2]));
        } else {
            tcop_set_desired_logic_sub_state(c, (eLogicSubState)num(a[2]));
        }
        printf("%s %s %s\n", o, a[1], a[2]);
    } else if (!strcmp(o, "clearp")) {
        taicop_clear_pursuit((tAICop *)(void *)m->Cops[atoi(a[1])]);
        printf("clearp %s\n", a[1]);
    } else if (!strcmp(o, "clearst")) {
        taicop_clear_speed_trap((tAICop *)(void *)m->Cops[atoi(a[1])]);
        printf("clearst %s\n", a[1]);
    } else if (!strcmp(o, "strap")) {
        tAICop *c = (tAICop *)(void *)m->Cops[atoi(a[1])];
        int     i = atoi(a[2]);

        if (i < 0) {
            c->pMySpeedTrap = NULL;
        } else {
            c->pMySpeedTrap = &m->SpeedTraps[i];
            m->SpeedTraps[i].cop = &c->Base;
        }
    } else if (!strcmp(o, "state")) {
        m->Cops[atoi(a[1])]->LogicState = (eLogicState)num(a[2]);
    } else if (!strcmp(o, "cpos")) {
        Car *car = m->Cops[atoi(a[1])]->pMyCar;

        car->State.Position.x = bf(num(a[2]));
        car->State.Position.y = bf(num(a[3]));
    } else if (!strcmp(o, "cdmg")) {
        Car *car = m->Cops[atoi(a[1])]->pMyCar;

        car->pCarDamage = num(a[2]) ? (CarDamage *)(void *)dmg_token : NULL;
    } else if (!strcmp(o, "pursuit")) {
        int k = atoi(a[2]);

        pursuits[atoi(a[1])].pChasedCar = k >= 0 ? &cars[k] : NULL;
    } else if (!strcmp(o, "respk")) {
        respk = atoi(a[1]);
    } else if (!strcmp(o, "disable")) {
        disabling = m->Cops[atoi(a[1])];
        taicop_disable_my_car((tAICop *)(void *)disabling,
                              (int32_t)num(a[2]));
        printf("disable %s %d\n", a[1], (int32_t)num(a[2]));
    } else if (!strcmp(o, "zinit")) {
        init_zone_permission_table();
        printf("zinit\n");
    } else if (!strcmp(o, "zdump")) {
        int j;

        printf("Z");
        for (j = 0; j < 36; j++)
            printf(" %d", nZonePermissionTable[j]);
        printf("\n");
    } else if (!strcmp(o, "zset")) {
        nZonePermissionTable[atoi(a[1])] = (int32_t)num(a[2]);
    } else if (!strcmp(o, "zreq")) {
        printf("zreq %s %s -> %d\n", a[1], a[2],
               request_zone_permission((int32_t)num(a[1]),
                                       (int32_t)num(a[2])));
    } else if (!strcmp(o, "zget")) {
        printf("zget %s %08x -> %d\n", a[1], hex(a[2]),
               get_zone_from_sub_state((eLogicSubState)num(a[1]),
                                       bf(hex(a[2]))));
    } else if (!strcmp(o, "tcop") || !strcmp(o, "pcop")
               || !strcmp(o, "acop")) {
        int   k = atoi(a[1]);
        void *c = block(256);
        void *r;

        name(c, "R%d", nr++);
        if (!strcmp(o, "tcop"))
            r = tcop_construct(c, (int32_t)num(a[2]));
        else if (!strcmp(o, "pcop"))
            r = tplayercop_construct(c, &cars[atoi(a[3])],
                                     (int32_t)num(a[2]));
        else
            r = taicop_construct(c, info(a[2]), (int32_t)num(a[3]));
        m->Cops[k] = c;
        printf("%s %d -> %s\n", o, k, sym(r));
    } else if (!strcmp(o, "qroute")) {
        int q = atoi(a[1]);

        qroutes[q].RouteNumber = (int16_t)atoi(a[2]);
        qcount[q] = atoi(a[3]);
        qlink[q] = atoi(a[4]);
    } else if (!strcmp(o, "qpt")) {
        uint8_t *pt = (uint8_t *)qpoint(atoi(a[1]), atoi(a[2]));
        int      j;

        for (j = 0; j < 28; j++) {
            uint32_t w = hex(a[3 + j]);

            memcpy(pt + 4 * j, &w, 4);
        }
    } else if (!strcmp(o, "nearq")) {
        int j;

        nnear = (na - 1) / 3;
        near_at = 0;
        for (j = 0; j < nnear; j++) {
            nearq[j][0] = atoi(a[1 + 3 * j]);
            nearq[j][1] = atoi(a[2 + 3 * j]);
            nearq[j][2] = atoi(a[3 + 3 * j]);
        }
    } else if (!strcmp(o, "carq")) {
        int k = atoi(a[1]);

        car_q[k] = atoi(a[2]);
        car_i[k] = atoi(a[3]);
    } else if (!strcmp(o, "mycar")) {
        int k = atoi(a[2]);

        m->Cops[atoi(a[1])]->pMyCar = k >= 0 ? &cars[k] : NULL;
    } else if (!strcmp(o, "dl")) {
        tAICop *c = (tAICop *)(void *)m->Cops[atoi(a[1])];

        c->MyDLOffset.x = bf(hex(a[2]));
        c->MyDLOffset.y = bf(hex(a[3]));
        c->nDrivingLineIndex = (int32_t)num(a[4]);
    } else if (!strcmp(o, "rinfo")) {
        tAICop *c = (tAICop *)(void *)m->Cops[atoi(a[1])];
        int     q = atoi(a[2]);

        c->RouteInfo.Route = q >= 0 ? &qroutes[q] : NULL;
        c->RouteInfo.Point = qpoint(q, atoi(a[3]));
    } else if (!strcmp(o, "lss")) {
        m->Cops[atoi(a[1])]->LogicSubState = (eLogicSubState)num(a[2]);
    } else if (!strcmp(o, "wpos")) {
        Car *c = &cars[atoi(a[1])];

        c->State.Position.x = bf(hex(a[2]));
        c->State.Position.y = bf(hex(a[3]));
    } else if (!strcmp(o, "isnear")) {
        printf("isnear %s -> %d\n", a[1], taicop_is_near_pursuit_target(
                   (tAICop *)(void *)m->Cops[atoi(a[1])]));
    } else if (!strcmp(o, "initdt") || !strcmp(o, "upddt")) {
        tAICop *c = (tAICop *)(void *)m->Cops[atoi(a[1])];

        if (!strcmp(o, "initdt")) {
            taicop_initialize_drive_target(c);
        } else {
            dtpos.x = bf(hex(a[2]));
            dtpos.y = bf(hex(a[3]));
            taicop_update_drive_target(c, &dtpos, (int32_t)num(a[4]));
        }
        printf("%s %s ri %s", o, a[1], sym(c->RouteInfo.Route));
        printf(" %s", sym(c->RouteInfo.Point));
        if (c->Base.pMyCar != NULL) {
            const DriveTarget *t = &c->Base.pMyCar->pCarDriver->MyDriveTarget;

            printf(" pt0 %08x %08x", fb(t->Points[0].x), fb(t->Points[0].y));
        }
        printf("\n");
    } else if (!strcmp(o, "rig")) {
        // A world car made ready for a cop to drive: a CopDriver, a
        // CopMover not in the air, a collision body, and its driver on
        // the NullDriver's table.
        int        j = atoi(a[1]);
        Car       *c = &cars[j];
        CopDriver *k = block(sizeof(CopDriver));
        CopMover  *mv = block(sizeof(CopMover));
        void      *cb = block(96);

        name(k, "KJ%d", j);
        name(mv, "MV%d", j);
        name(cb, "CB%d", j);
        mv->bIsAirborne = 0;
        c->pCarController = (CarController *)(void *)k;
        c->pCarMover = (CarMover *)(void *)mv;
        c->pDynamicCollisionBody = cb;
        ((CollisionBody *)cb)->_vtable = CB_VT;
        drivers[j]._vtable = NULLDRIVER_VTABLE;
    } else if (!strcmp(o, "cf")) {
        car_field(&cars[atoi(a[1])], a[2], hex(a[3]));
    } else if (!strcmp(o, "df")) {
        driver_field(&drivers[atoi(a[1])], a[2], hex(a[3]));
    } else if (!strcmp(o, "kf")) {
        ((CopDriver *)(void *)cars[atoi(a[1])].pCarController)->State =
            (eCopDriverStates)hex(a[2]);
    } else if (!strcmp(o, "af")) {
        cop_field((tAICop *)(void *)m->Cops[atoi(a[1])], a[2], hex(a[3]));
    } else if (!strcmp(o, "g")) {
        if (!strcmp(a[1], "wte"))
            WorldTimeElapsed = bf(hex(a[2]));
        else if (!strcmp(a[1], "camf"))
            CameraFollowThisCarInstead = (int32_t)hex(a[2]);
        else if (!strcmp(a[1], "reqp"))
            reqp_answer = hex(a[2]);
        else
            dist_answer = bf(hex(a[2]));
    } else if (!strcmp(o, "mdmg")) {
        m->fCarDamage[atoi(a[1])] = bf(hex(a[2]));
    } else if (!strcmp(o, "think")) {
        tCop          *c = m->Cops[atoi(a[1])];
        const VtEntry *e = slot(c, TCOP_VT_THINK);

        ((void (*)(void *))e->fn)(vt_this(c, e));
        printf("think %s\n", a[1]);
    } else if (!strcmp(o, "hst")) {
        taicop_handle_state_transitions(
            (tAICop *)(void *)m->Cops[atoi(a[1])], (eLogicState)num(a[2]),
            (eLogicState)num(a[3]));
        printf("hst %s %s %s\n", a[1], a[2], a[3]);
    } else if (!strcmp(o, "mmt")) {
        taicop_movement_mode_transitions(
            (tAICop *)(void *)m->Cops[atoi(a[1])]);
        printf("mmt %s\n", a[1]);
    } else if (!strcmp(o, "tdump")) {
        tdump(atoi(a[1]));
    } else if (!strcmp(o, "wcount")) {
        world.TotalNumCars = (int32_t)num(a[1]);
        world.CopCarPos = (int32_t)num(a[2]);
    } else if (!strcmp(o, "distq")) {
        int j;

        ndistq = na - 1;
        distq_at = 0;
        for (j = 0; j < ndistq; j++)
            distq[j] = bf(hex(a[1 + j]));
    } else if (!strcmp(o, "coll")) {
        int j = atoi(a[1]), i;

        cars[j].pDynamicCollisionBody->Dynamic.Body.NumCollisions =
            (int8_t)atoi(a[2]);
        coll_n[j] = na - 3;
        for (i = 0; i < coll_n[j]; i++)
            sscanf(a[3 + i], "%d:%d:%d", &coll_two[j][i], &coll_a[j][i],
                   &coll_b[j][i]);
    } else if (!strcmp(o, "front")) {
        if (!strcmp(a[1], "clear"))
            memset(front, 0, sizeof front);
        else
            front[atoi(a[1])][atoi(a[2])] = atoi(a[3]);
    } else if (!strcmp(o, "pidx")) {
        m->nPlayerCopIndex = (int32_t)num(a[1]);
    } else if (!strcmp(o, "pull")) {
        m->CarPullovers[atoi(a[1])].bActive = (int32_t)num(a[2]);
    } else if (!strcmp(o, "ptimer")) {
        m->fPursuableTimer[atoi(a[1])] = bf(hex(a[2]));
    } else if (!strcmp(o, "plist")) {
        tPursuitNode *prev = &m->PursuitList;
        int           j;

        for (j = 1; j < na; j++) {
            tPursuitNode *n = &pursuits[atoi(a[j])].Node;

            prev->Next = n;
            n->Prev = prev;
            prev = n;
        }
        prev->Next = &m->PursuitList;
        m->PursuitList.Prev = prev;
    } else if (!strcmp(o, "prb")) {
        int r = atoi(a[2]);

        pursuits[atoi(a[1])].pRoadBlock = r >= 0 ? &m->RoadBlocks[r] : NULL;
    } else if (!strcmp(o, "rbspot")) {
        tRoadBlock *rb = &m->RoadBlocks[atoi(a[1])];
        int         i = atoi(a[2]);

        rb->CopPos[i].x = bf(hex(a[3]));
        rb->CopPos[i].y = bf(hex(a[4]));
        rb->CopAng[i] = (uint16_t)atoi(a[5]);
    } else if (!strcmp(o, "tele")) {
        dtpos.x = bf(hex(a[2]));
        dtpos.y = bf(hex(a[3]));
        taicop_teleport((tAICop *)(void *)m->Cops[atoi(a[1])], &dtpos,
                        (uint16_t)num(a[4]));
        printf("tele %s\n", a[1]);
    } else if (!strcmp(o, "settrap")) {
        taicop_set_speed_trap((tAICop *)(void *)m->Cops[atoi(a[1])],
                              &m->SpeedTraps[atoi(a[2])]);
        printf("settrap %s %s\n", a[1], a[2]);
    } else if (!strcmp(o, "setrb")) {
        int k = atoi(a[3]);

        taicop_set_road_block((tAICop *)(void *)m->Cops[atoi(a[1])],
                              &m->RoadBlocks[atoi(a[2])],
                              k >= 0 ? &pursuits[k] : NULL,
                              (int32_t)num(a[4]));
        printf("setrb %s %s %s %s\n", a[1], a[2], a[3], a[4]);
    } else if (!strcmp(o, "valid")) {
        int32_t r = taicop_is_valid_pursuit_target(
            (tAICop *)(void *)m->Cops[atoi(a[1])], &cars[atoi(a[2])],
            (int32_t)num(a[3]));

        printf("valid %s %s %s -> %d\n", a[1], a[2], a[3], r & 0xff);
    } else if (!strcmp(o, "see")) {
        printf("see %s %s -> %d\n", a[1], a[2],
               taicop_can_patroller_see_this_car(
                   (tAICop *)(void *)m->Cops[atoi(a[1])], &cars[atoi(a[2])]));
    } else if (!strcmp(o, "listrap") || !strcmp(o, "liroad")
               || !strcmp(o, "lstrap") || !strcmp(o, "lroad")
               || !strcmp(o, "lpatrol")) {
        tAICop *c = (tAICop *)(void *)m->Cops[atoi(a[1])];

        if (!strcmp(o, "listrap"))
            taicop_init_speed_trap_logic(c);
        else if (!strcmp(o, "liroad"))
            taicop_init_road_block_logic(c);
        else if (!strcmp(o, "lstrap"))
            taicop_do_speed_trap_logic(c);
        else if (!strcmp(o, "lroad"))
            taicop_do_road_block_logic(c);
        else
            taicop_do_driving_on_patrol_logic(c);
        printf("%s %s\n", o, a[1]);
    } else if (!strcmp(o, "canteleport")) {
        dtpos.x = bf(hex(a[2]));
        dtpos.y = bf(hex(a[3]));
        printf("canteleport %s -> %d\n", a[1],
               can_teleport(&cars[atoi(a[1])], &dtpos));
    } else if (!strcmp(o, "caused")) {
        Car *r = car_caused_recent_collision(&cars[atoi(a[1])]);

        printf("caused %s -> %s\n", a[1], sym(r));
    } else if (!strcmp(o, "pcops")) {
        tPursuit *p = &pursuits[atoi(a[1])];
        int       j;

        for (j = 0; j < 2; j++) {
            int c = atoi(a[2 + j]);

            p->Cops[j] = c >= 0 ? m->Cops[c] : NULL;
        }
    } else if (!strcmp(o, "mdiff")) {
        m->nDifficultyLevel = (int32_t)num(a[1]);
    } else if (!strcmp(o, "pflags")) {
        pursuits[atoi(a[1])].BehaviourFlags = hex(a[2]);
    } else if (!strcmp(o, "tlen")) {
        TheTrackPathManager.TrackLength = bf(hex(a[1]));
    } else if (!strcmp(o, "randi")) {
        int j;

        nrandi = na - 1;
        randi_at = 0;
        for (j = 0; j < nrandi; j++)
            randi_q[j] = (int32_t)num(a[1 + j]);
    } else if (!strcmp(o, "randf")) {
        int j;

        nrandf = na - 1;
        randf_at = 0;
        for (j = 0; j < nrandf; j++)
            randf_q[j] = hex(a[1 + j]);
    } else if (!strcmp(o, "w2c")) {
        int j;

        nw2c = (na - 1) / 2;
        w2c_at = 0;
        for (j = 0; j < nw2c; j++) {
            w2c_q[j][0] = hex(a[1 + 2 * j]);
            w2c_q[j][1] = hex(a[2 + 2 * j]);
        }
    } else if (!strcmp(o, "lhot") || !strcmp(o, "lcaught")
               || !strcmp(o, "rtp")) {
        tAICop *c = (tAICop *)(void *)m->Cops[atoi(a[1])];

        if (!strcmp(o, "lhot"))
            taicop_do_hot_pursuit_logic(c);
        else if (!strcmp(o, "lcaught"))
            taicop_do_caught_speeder_logic(c);
        else
            taicop_return_to_patrol(c);
        printf("%s %s\n", o, a[1]);
    } else if (!strcmp(o, "bfs")) {
        float r = taicop_get_best_flank_side(
            (tAICop *)(void *)m->Cops[atoi(a[1])], &cars[atoi(a[2])]);

        printf("bfs %s %s -> %08x\n", a[1], a[2], fb(r));
    } else if (!strcmp(o, "new")) {
        printf("new -> %s\n", sym(taicop_new()));
    } else if (!strcmp(o, "del")) {
        taicop_delete(m->Cops[atoi(a[1])]);
        printf("del %s\n", a[1]);
    } else {
        fprintf(stderr, "unknown op %s\n", o);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[1 << 16];
    FILE       *f;
    int         i;

    if (argc != 2) {
        fprintf(stderr, "usage: cop_test script.txt\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    name(pool_token, "pool", 0);
    name(player_token, "PL", 0);
    name(dmg_token, "DMG", 0);
    name(&world, "W", 0);
    for (i = 0; i < NCARS; i++) {
        name(&cars[i], "A%d", i);
        name(&drivers[i], "V%d", i);
        memset(&drivers[i], 0xcd, sizeof drivers[i]);
        cars[i].pCarDriver = &drivers[i];
        car_q[i] = -1;
        car_i[i] = -1;
    }
    for (i = 0; i < NQ; i++) {
        name(&qroutes[i], "Q%d", i);
        qlink[i] = -1;
    }
    for (i = 0; i < 4; i++) {
        name(&types[i], "T%d", i);
        name(&dinfo[i], "D%d", i);
    }
    for (i = 0; i < 5; i++) {
        name(&pursuits[i], "U%d", i);
        memset(&pursuits[i], 0xcd, sizeof pursuits[i]);
        pursuits[i].pRoadBlock = NULL;
        pursuits[i].Cops[0] = NULL;
        pursuits[i].Cops[1] = NULL;
        pursuits[i].BehaviourFlags = 0;
    }
    for (i = 0; i < NCARS * NCOLS; i++)
        name(coltok[i / NCOLS][i % NCOLS], "X%d", 10 * (i / NCOLS) + i % NCOLS);
    pCurrentWorld = &world;
    CopSlotPool = (BSlotPool *)(void *)pool_token;
    gPursuitRemoveCopFromPursuitFn = rmcop;
    gPursuitRemovePrimarySpeakerFn = rmspk;
    gCarDamageWreckFn = wreck;
    gCarDamageRepairAllFn = repair;
    gCopManagerRequestPursuitFn = reqp;
    gPlayerCopThinkFn = pthink;
    name(&TheDriveTargetRenderer, "DTR", 0);
    nd_vt[CARDRIVER_VT_SET_DESIRED_SPEED / 8].fn = (VtFn)nd_speed;
    vt_install(NULLDRIVER_VTABLE, nd_vt, CARDRIVER_VT_ENTRIES);
    cb_vt[COLLISIONBODY_VT_SET_TO_PHYSICS_MODE / 8].fn = (VtFn)cb_physmode;
    cb_vt[COLLISIONBODY_VT_APPLY_IMPULSE / 8].fn = (VtFn)cb_impulse;
    vt_install(CB_VT, cb_vt, COLLISIONBODY_VT_ENTRIES);
    cop_install_vtables();
    copmgr_install_vtables();
    while (fgets(line, sizeof line, f) != NULL) {
        char *a[64], *s = line;
        int   na = 0;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        while (na < 64) {
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
