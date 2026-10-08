// Harness for tools/cop_check.py: runs the checker's script on cop.c --
// tCop, tPlayerCop and tAICop's constructors and destructors, the setters,
// ClearPursuit, ClearSpeedTrap, DisableMyCar, the zones, the drive
// target (IsNearPursuitTarget, InitializeDriveTarget, UpdateDriveTarget)
// and tAICop::Think with its transitions and the limbo, disabled and
// guard logic -- and on copmgr.c's CreateCop, 0x002276a0,
// AddCopCarToRace and ResetAllDamage, and prints what the model prints
// for the retail image. See the checker's docstring.
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
#include "cartypeinfo.h"
#include "collision.h"
#include "collisionbody.h"
#include "cardriver.h"
#include "configitems.h"
#include "cop.h"
#include "copdriver.h"
#include "copmgr.h"
#include "drivetarget.h"
#include "drivetargetrenderer.h"
#include "race.h"
#include "racecoord.h"
#include "realdriver.h"
#include "realtime.h"
#include "topology.h"
#include "trackgraph.h"
#include "trackmap.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

// Retail's sizeof(Car), which its bMalloc is asked for.
#define RETAIL_CAR_SIZE 2208

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

// What World's distance to the nearest player answers, from the script.
static float dist_answer;

void trackgraph_uncloak_all_edges(tTrackGraph *g)
{
    (void)g;
    abort();
}

float world_get_distance_to_closest_player_2d(const World *w,
                                              const bVector2 *pos)
{
    printf("  dist %s %08x %08x -> %08x\n", sym(w), fb(pos->x), fb(pos->y),
           fb(dist_answer));
    return dist_answer;
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

void realdriver_force_ebrake_stop(RealDriver *d, int32_t on)
{
    printf("  ebrake %s %08x\n", sym(d), (uint32_t)on);
}

#define NCARS 4

static World       world;
static Car         cars[NCARS];
static CarTypeInfo types[4];
static DriverInfo  dinfo[4];
static tPursuit    pursuits[4];
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

float world_random_f(World *w, float f)
{
    (void)w; (void)f;
    unreached("world_random_f");
    return 0.0f;
}

int32_t is_point_in_poly(const bVector2 *p, const bVector2 *poly, int32_t n)
{
    (void)p; (void)poly; (void)n;
    unreached("is_point_in_poly");
    return 0;
}

struct Collision *collisionbody_get_collision(CollisionBody *b, int32_t i)
{
    (void)b; (void)i;
    unreached("collisionbody_get_collision");
    return NULL;
}

int32_t collision_is_two_car_collision(Collision *c)
{
    (void)c;
    unreached("collision_is_two_car_collision");
    return 0;
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

// The logic not ported yet, each logged by its name.
static void logic(const char *what, tAICop *c)
{
    printf("  logic %s %s\n", what, sym(c));
}

static void l_istrap(tAICop *c) { logic("istrap", c); }
static void l_iroad(tAICop *c) { logic("iroad", c); }
static void l_strap(tAICop *c) { logic("strap", c); }
static void l_road(tAICop *c) { logic("road", c); }
static void l_patrol(tAICop *c) { logic("patrol", c); }
static void l_hot(tAICop *c) { logic("hot", c); }
static void l_caught(tAICop *c) { logic("caught", c); }

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
    printf(" st %s\n", sym(a->pMySpeedTrap));
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
        void      *cb = block(64);

        name(k, "KJ%d", j);
        name(mv, "MV%d", j);
        name(cb, "CB%d", j);
        mv->bIsAirborne = 0;
        c->pCarController = (CarController *)(void *)k;
        c->pCarMover = (CarMover *)(void *)mv;
        c->pDynamicCollisionBody = cb;
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
        name(&pursuits[i], "U%d", i);
        memset(&pursuits[i], 0xcd, sizeof pursuits[i]);
    }
    pCurrentWorld = &world;
    CopSlotPool = (BSlotPool *)(void *)pool_token;
    gPursuitRemoveCopFromPursuitFn = rmcop;
    gPursuitRemovePrimarySpeakerFn = rmspk;
    gCarDamageWreckFn = wreck;
    gCarDamageRepairAllFn = repair;
    gAICopInitSpeedTrapLogicFn = l_istrap;
    gAICopInitRoadBlockLogicFn = l_iroad;
    gAICopDoSpeedTrapLogicFn = l_strap;
    gAICopDoRoadBlockLogicFn = l_road;
    gAICopDoDrivingOnPatrolLogicFn = l_patrol;
    gAICopDoHotPursuitLogicFn = l_hot;
    gAICopDoCaughtSpeederLogicFn = l_caught;
    gPlayerCopThinkFn = pthink;
    name(&TheDriveTargetRenderer, "DTR", 0);
    nd_vt[CARDRIVER_VT_SET_DESIRED_SPEED / 8].fn = (VtFn)nd_speed;
    vt_install(NULLDRIVER_VTABLE, nd_vt, CARDRIVER_VT_ENTRIES);
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
