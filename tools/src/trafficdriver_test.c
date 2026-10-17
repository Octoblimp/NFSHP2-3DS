// Harness for tools/trafficdriver_check.py: runs the checker's op script on
// the port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out, and stands in for what the checker stubs.
//
//     trafficdriver_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "aiaction.h"
#include "aiactions.h"
#include "aicarcontroller.h"
#include "aidriver.h"
#include "bmem.h"
#include "car.h"
#include "cardriver.h"
#include "drivetarget.h"
#include "drivetargetrenderer.h"
#include "drivingchoice.h"
#include "drivinglocation.h"
#include "nearbycar.h"
#include "psychodriver.h"
#include "realtime.h"
#include "trackroute.h"
#include "trafficdriver.h"
#include "vtable.h"
#include "world.h"

// The DoSnapshots (TASKS 72c) call these; nothing here takes a
// snapshot.
static void snapshot_unreached(const char *f)
{
    fprintf(stderr, "%s reached\n", f);
    exit(3);
}

void aicarcontroller_do_snapshot(AICarController *c, struct ReplaySnapshot *s)
{
    (void)c; (void)s;
    snapshot_unreached("aicarcontroller_do_snapshot");
}

enum {
    OP_TAG, OP_JUNK, OP_NEW, OP_DEL, OP_NULL, OP_RAWDEL, OP_THINK, OP_ROUTES,
    OP_RESET, OP_EXEC, OP_SPEED, OP_DIR, OP_SET, OP_CUR, OP_POKE, OP_GLOBAL,
    OP_PT, OP_FILL, OP_ROUTE, OP_RPOINT, OP_SIGN, OP_LOC, OP_WORLD, OP_TABLE,
    OP_DUMP, OP_STATIC
};

enum {
    K_MASK, K_HIT, K_AVOIDCAR, K_SECS, K_OKAY, K_USED, K_ACH_TYPE, K_ACH_CAR,
    K_ACH_EXTRA, K_STATUS, K_CANEXPIRE, K_BIAS, K_GCTRP, K_LINE, K_NPTS,
    K_DSPEED, K_DTIME, K_DTOL, K_USEDLS, K_ALLOWED, K_SCORE,
    K_COUNT = K_SCORE + 6
};

enum { S_UNSTUCK, S_RECOVERY, S_HIT, S_AVOID, S_PULLOVER, S_DRIVE };

enum {
    W_HIT = 1 << 0, W_AVOIDCAR = 1 << 1, W_SECS = 1 << 2, W_OKAY = 1 << 3,
    W_USED = 1 << 4, W_ACH = 1 << 5
};

enum {
    P_TIMER, P_LOOP, P_LAST, P_SECS, P_PICK, P_DTYPE, P_CARIDX, P_DRVNUM,
    P_MODE, P_LOCSEL, P_LIST, P_CHOICE_TYPE, P_CAMCAR, P_CAMDEF,
    P_LOOKAHEAD, P_FORCE, P_CUR_TYPE, P_CUR_SCORE, P_CUR_STATUS,
    P_CUR_CANEXP
};

#define NO_CAR   (-1)
#define NCARS    8
#define MY_CAR   NCARS
#define NSLOTS   64
#define NROUTES  4
#define NSIGNS   256     // every index a point's byte can give
#define NPTS     DRIVETARGET_MAX_POINTS
#define SLACK    16
#define MAX_HEAP 16384

// AICarController's retail table, which the stand-in constructor stores,
// and the test tables the driver and the actions are given.
#define AICC_RETAIL_VT  0x002b4d90u
#define FAKE_DRIVER_VT  0x01e0a000u
#define FAKE_ACTION_VT  0x01e0b000u

// ------------------------------------------------------------- the world

static union {
    TrafficDriver d;
    unsigned char b[sizeof(TrafficDriver)];
} du;
static TrafficDriver *const d = &du.d;

static Car             car;
static DriverInfo      drv;
static World           world;
static char            cars[NCARS][16];
static char            list_mem[16];
static DrivingLocation loc;
static DrivingChoice   choice_obj;
static union {
    AIAction a;
    double   align;
    char     b[1024];
} cur_mem;
static union {
    AIAction a;
    double   align;
    char     b[1024];
} slot_mem[NSLOTS];
static int nslots;
static TrackRoute routes[NROUTES];
static Signpost   signs[NSIGNS];

// What the linked files leave to the game.
int32_t             WorldTimer;
int32_t             WorldLoopCounter;
World              *pCurrentWorld;
DriveTargetRenderer TheDriveTargetRenderer;
float               AIDriverSecondsToLookAhead = 2.0f;
int32_t             CameraFollowDefaultCar = 1;
int32_t             CameraFollowThisCarInstead = -1;

// aidriver.c's and aiaction.c's, at retail's values: the checker's static
// dump reads them back against the image's.
int32_t AIActionJustDriveScore;
int32_t AIActionAvoidCarsScore = 400;
int32_t AIActionIJustGotHitScore = 400;
int32_t AIActionGetUnstuckScore = 500;
int32_t AIActionAccidentRecoveryScore = 500;
int32_t AIActionPullOverScore = 600;
float   AIActionGetUnstuckLifetime = 5.0f;
float   AIActionAvoidCarsLifetime;
float   AIActionIJustGotHitLifetime;
float   AIActionPullOverTrafficCarTimeout = -999.0f;

static uint32_t vals[K_COUNT];
static float    pts[NPTS][2];

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

static Car *car_of(int32_t i)
{
    if (i == NO_CAR)
        return NULL;
    if (i == MY_CAR)
        return &car;
    if (i < 0 || i >= NCARS) {
        fprintf(stderr, "no car %d\n", i);
        exit(2);
    }
    return (Car *)(void *)cars[i];
}

static TrackRoute *route_of(int32_t k)
{
    if (k < 0)
        return NULL;
    if (k >= NROUTES) {
        fprintf(stderr, "no route %d\n", k);
        exit(2);
    }
    return &routes[k];
}

static DrivingLocation *myloc(void)
{
    return &d->Base.MyCurrentDrivingInformation.MyDrivingLocation;
}

// ------------------------------------------------------------- the heap

static struct {
    const void *p;
    size_t      span;
} heap[MAX_HEAP];
static int nheap;

// The console's size of what the port asked for: its PsychoDriver is wider
// on a 64-bit host.
static int console_size(int size, const char *name)
{
    if (strcmp(name, "PsychoDriver") == 0 && size == (int)sizeof(PsychoDriver))
        return 624;
    return size;
}

static void *malloc_hook(int size, const char *name, int flags, int pool)
{
    size_t span = (size > 0 ? (size_t)size : 0) + SLACK;
    void  *p = malloc(span);

    if (nheap >= MAX_HEAP) {
        fprintf(stderr, "heap log full\n");
        exit(3);
    }
    memset(p, 0xcd, span);
    heap[nheap].p = p;
    heap[nheap].span = span;
    printf("  alloc h%d size %d name %s flags %d pool %d\n", nheap,
           console_size(size, name), name, flags, pool);
    nheap++;
    return p;
}

static void label(char *buf, size_t n, const void *a)
{
    static const struct {
        const void *p;
        const char *name;
    } named[] = {
        { &du, "d" },
        { &du.d.Base.MyCurrentDrivingInformation, "info" },
        { &du.d.Base.MyCurrentDrivingInformation.MyDrivingLocation, "myloc" },
        { &car, "car" },
        { &world, "world" },
        { list_mem, "list" },
        { &loc, "loc" },
        { &choice_obj, "choice" },
        { &TheDriveTargetRenderer, "renderer" },
    };
    const char *b = (const char *)a;
    size_t k;
    int i;

    if (a == NULL) {
        snprintf(buf, n, "null");
        return;
    }
    for (k = 0; k < sizeof named / sizeof named[0]; k++)
        if (a == named[k].p) {
            snprintf(buf, n, "%s", named[k].name);
            return;
        }
    for (i = 0; i < NCARS; i++)
        if (a == (const void *)cars[i]) {
            snprintf(buf, n, "c%d", i);
            return;
        }
    if (b >= cur_mem.b && b < cur_mem.b + sizeof(AIAction)) {
        if (b == cur_mem.b)
            snprintf(buf, n, "cur");
        else
            snprintf(buf, n, "cur+%d", (int)(b - cur_mem.b));
        return;
    }
    for (i = 0; i < NSLOTS; i++) {
        const char *p = slot_mem[i].b;
        if (b >= p && b < p + sizeof(AIAction)) {
            if (b == p)
                snprintf(buf, n, "a%d", i);
            else
                snprintf(buf, n, "a%d+%d", i, (int)(b - p));
            return;
        }
    }
    for (i = 0; i < NROUTES; i++) {
        const char *p = (const char *)&routes[i];
        if (b >= p && b < p + sizeof(TrackRoute)) {
            ptrdiff_t off = b - p;
            ptrdiff_t t = (ptrdiff_t)offsetof(TrackRoute, TrackRoutePointTable);
            if (off == 0)
                snprintf(buf, n, "r%d", i);
            else if (off >= t
                     && (off - t) % (ptrdiff_t)sizeof(TrackRoutePoint) == 0)
                snprintf(buf, n, "r%dp%d", i,
                         (int)((off - t) / (ptrdiff_t)sizeof(TrackRoutePoint)));
            else
                snprintf(buf, n, "r%d+%d", i, (int)off);
            return;
        }
    }
    for (i = 0; i < NSIGNS; i++)
        if (a == (const void *)&signs[i]) {
            snprintf(buf, n, "s%d", i);
            return;
        }
    for (i = 0; i < nheap; i++) {
        const char *p = (const char *)heap[i].p;
        if (b >= p && b < p + heap[i].span) {
            if (b == p)
                snprintf(buf, n, "h%d", i);
            else
                snprintf(buf, n, "h%d+%d", i, (int)(b - p));
            return;
        }
    }
    snprintf(buf, n, "?");
}

static const char *lab(const void *a)
{
    static char bufs[16][48];
    static int k;
    char *b = bufs[k++ & 15];

    label(b, 48, a);
    return b;
}

// Logged, never freed, so no address is handed out twice.
static void free_hook(void *p)
{
    printf("  free %s\n", lab(p));
}

// ------------------------------------------------------------ stand-ins

AICarController *aicarcontroller_init(AICarController *c, Car *cr)
{
    printf("  aicc init %s %s\n", lab(c), lab(cr));
    c->Base.pCar = cr;
    c->Base._vtable = AICC_RETAIL_VT;
    return c;
}

void aicarcontroller_destroy(AICarController *c, int32_t flags)
{
    printf("  aicc dtor %s %d\n", lab(c), flags);
}

void aicarcontroller_do_sticky_decisions(AICarController *c)
{
    printf("  sticky %s\n", lab(c));
}

void aicarcontroller_clear_sticky_decisions(AICarController *c)
{
    printf("  clearsticky %s\n", lab(c));
}

// What the script says becomes of the current location's route: -2 left
// alone, -1 cleared, else route k at its first point.
void aicarcontroller_get_current_track_route_point(AICarController *c,
                                                   Car *cr)
{
    int32_t k = (int32_t)vals[K_GCTRP];

    printf("  gctrp %s %s\n", lab(c), lab(cr));
    if (k == -2)
        return;
    c->CurrentDrivingLocation->pRoute = route_of(k);
    if (k >= 0)
        c->CurrentDrivingLocation->pRoutePoint =
            &routes[k].TrackRoutePointTable[0];
}

void aicarcontroller_maybe_honk_and_or_blink_headlights(AICarController *c,
                                                        Car *cr,
                                                        NearbyCarList *list)
{
    printf("  honk %s %s %s\n", lab(c), lab(cr), lab(list));
}

// aicarcontroller.c's (0x001908f0), which needs most of the AI to link.
int32_t aicarcontroller_get_my_driver_number(AICarController *c)
{
    return c->Base.pCar->DriverNumber;
}

// The table's other entries: in the table, never called here.
static void never(const char *what)
{
    fprintf(stderr, "%s called\n", what);
    exit(4);
}

void aicarcontroller_debug_display(AICarController *c)
{
    (void)c;
    never("debug_display");
}

void aicarcontroller_set_current_route(AICarController *c, TrackRoute *r,
                                       TrackRoutePoint *p)
{
    (void)c; (void)r; (void)p;
    never("set_current_route");
}

TrackRoute *aicarcontroller_get_current_route(AICarController *c, int find)
{
    (void)c; (void)find;
    never("get_current_route");
    return NULL;
}

TrackRoutePoint *aicarcontroller_get_current_route_point(AICarController *c,
                                                         int find)
{
    (void)c; (void)find;
    never("get_current_route_point");
    return NULL;
}

float aicarcontroller_get_amount_out_of_bounds(AICarController *c)
{
    (void)c;
    never("get_amount_out_of_bounds");
    return 0.0f;
}

void aicarcontroller_find_where_i_am(AICarController *c)
{
    (void)c;
    never("find_where_i_am");
}

void aicarcontroller_set_to_physics_mode(AICarController *c, Car *cr)
{
    (void)c; (void)cr;
    never("set_to_physics_mode");
}

void aicarcontroller_force_boost(AICarController *c, float f)
{
    (void)c; (void)f;
    never("force_boost");
}

void aicarcontroller_release_boost(AICarController *c)
{
    (void)c;
    never("release_boost");
}

void aicarcontroller_choose_new_action(AICarController *c, AIAction **out,
                                       AIActionType type)
{
    (void)c; (void)out; (void)type;
    never("choose_new_action");
}

void aicarcontroller_generate_points_to_fulfill_action(AICarController *c,
                                                       AIAction *a)
{
    (void)c; (void)a;
    never("generate_points_to_fulfill_action");
}

// The driver's test table: the destructor (8), SetDesiredSpeed (56) and
// SetTarget (64).
static void fake_driver_dtor(void *self, int32_t flags)
{
    printf("  driver dtor %s %d\n", lab(self), flags);
}

static void fake_driver_speed(void *self, float speed, float time, float tol,
                              int32_t allowed)
{
    printf("  driver speed %s %08x %08x %08x %d\n", lab(self), bitsf(speed),
           bitsf(time), bitsf(tol), allowed);
}

static void fake_driver_target(void *self, const DriveTarget *t)
{
    printf("  driver target %s %s %d\n", lab(self), lab(t), t->NumPoints);
}

static const VtEntry fake_driver_vt[9] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)fake_driver_dtor },
    { 0, 0, NULL }, { 0, 0, NULL }, { 0, 0, NULL }, { 0, 0, NULL },
    { 0, 0, NULL },
    { 0, 0, (VtFn)fake_driver_speed },
    { 0, 0, (VtFn)fake_driver_target },
};

PsychoDriver *psychodriver_init(PsychoDriver *pd, Car *cr)
{
    printf("  psycho init %s %s\n", lab(pd), lab(cr));
    pd->Base._vtable = FAKE_DRIVER_VT;
    return pd;
}

// The script's points and speeds into an action, as the test table's
// CalculatePointsToDrive and OP_FILL write them.
static void fill(AIAction *a)
{
    int k;

    a->PointsToDrive.NumPoints = (int8_t)vals[K_NPTS];
    for (k = 0; k < NPTS; k++) {
        a->PointsToDrive.Points[k].x = pts[k][0];
        a->PointsToDrive.Points[k].y = pts[k][1];
    }
    a->DesiredSpeed = fbits(vals[K_DSPEED]);
    a->TimeToGetToDesiredSpeed = fbits(vals[K_DTIME]);
    a->DesiredSpeedTolerance = fbits(vals[K_DTOL]);
    a->UseDrivingLineSpeed = (int32_t)vals[K_USEDLS];
    a->AllowedToUseThrottleAndBrake = (int32_t)vals[K_ALLOWED];
}

// The actions' test table: the destructor (8) and CalculatePointsToDrive
// (24).
static void fake_action_dtor(void *self, int32_t flags)
{
    printf("  act dtor %s %d\n", lab(self), flags);
}

static void fake_action_points(void *self, DrivingInformation *info)
{
    printf("  act points %s %s\n", lab(self), lab(info));
    fill((AIAction *)self);
}

static const VtEntry fake_action_vt[4] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)fake_action_dtor },
    { 0, 0, NULL },
    { 0, 0, (VtFn)fake_action_points },
};

void nearbycarlist_build_array(NearbyCarList *l, DrivingLocation *lc,
                               float secs)
{
    printf("  build %s %s %08x\n", lab(l), lab(lc), bitsf(secs));
}

void ai_highlight_driving_line(DrivingLocation *lc, int32_t n)
{
    printf("  highlight %s %d\n", lab(lc), n);
}

void car_set_movement_mode(Car *c, MovementMode mode)
{
    printf("  mode %s %d\n", lab(c), (int32_t)mode);
    c->TheMovementMode = mode;
}

int32_t drivingchoice_get_driving_line(DrivingChoiceType type, Car *cr)
{
    int32_t r = (int32_t)vals[K_LINE];

    printf("  getline %d %s -> %d\n", (int32_t)type, lab(cr), r);
    return r;
}

void drivetargetrenderer_set_target_to_render(DriveTargetRenderer *r,
                                              DriveTarget *t)
{
    printf("  render %s %s\n", lab(r), lab(t));
}

void aiaction_update_status(AIAction *a, DrivingInformation *info)
{
    printf("  status %s %s\n", lab(a), lab(info));
    a->Base.Status = (PlanStatus)(int32_t)vals[K_STATUS];
    a->Base.CanExpire = (int32_t)vals[K_CANEXPIRE];
}

void aiaction_clear_points_to_drive(AIAction *a)
{
    printf("  clearpoints %s\n", lab(a));
}

void *aiaction_new(void)
{
    void *p;

    if (nslots >= NSLOTS) {
        fprintf(stderr, "out of action slots\n");
        exit(3);
    }
    p = &slot_mem[nslots++];
    printf("  oalloc pool -> %s\n", lab(p));
    return p;
}

// aiaction.c's (0x001cab48), inline in retail; checked by its checker.
int aiplan_time_to_change(const AIPlan *p)
{
    if (p == NULL)
        return 1;
    if (p->Status == STATUS_SUCCESS || p->Status == STATUS_FAILURE)
        return 1;
    return p->Status == STATUS_EXPIRED && p->CanExpire != 0;
}

// drivingchoice.c's, which needs most of the AI to link; checked by
// drivingchoice_check.py.
void drivingchoice_clear(DrivingChoice *c)
{
    c->UseExtraLateralDistance = 0;
    c->Type = CHOICE_NONE;
    c->pCar = NULL;
}

// ------------------------------------------------- the CalculateScores

static const char *choice_str(const DrivingChoice *c)
{
    static char bufs[4][64];
    static int k;
    char *b = bufs[k++ & 3];

    snprintf(b, 64, "%d %s %d", (int32_t)c->Type, lab(c->pCar),
             c->UseExtraLateralDistance);
    return b;
}

static int32_t score(int i, const char *name, DrivingInformation *info,
                     const char *extra)
{
    int32_t r = (int32_t)vals[K_SCORE + i];

    printf("  score %s %s%s -> %d\n", name, lab(info), extra, r);
    return r;
}

int32_t aigetunstuck_calculate_score(DrivingInformation *info)
{
    return score(S_UNSTUCK, "unstuck", info, "");
}

int32_t aiaccidentrecovery_calculate_score(DrivingInformation *info)
{
    return score(S_RECOVERY, "recovery", info, "");
}

int32_t aijustgothit_calculate_score(DrivingInformation *info, Car **cr)
{
    char b[64];
    int32_t r;

    snprintf(b, sizeof b, " car %s", lab(*cr));
    r = score(S_HIT, "hit", info, b);
    if (vals[K_MASK] & W_HIT)
        *cr = car_of((int32_t)vals[K_HIT]);
    return r;
}

int32_t aiavoidcars_calculate_score(DrivingInformation *info, Car **cr,
                                    DrivingChoice *choice, float *secs,
                                    int *okay, int *usedPreferred)
{
    char b[200];
    uint32_t m = vals[K_MASK];
    int32_t r;

    snprintf(b, sizeof b, " car %s choice %s secs %08x okay %d used %d",
             lab(*cr), choice_str(choice), bitsf(*secs), *okay,
             *usedPreferred);
    r = score(S_AVOID, "avoid", info, b);
    if (m & W_AVOIDCAR)
        *cr = car_of((int32_t)vals[K_AVOIDCAR]);
    if (m & W_ACH) {
        choice->Type = (DrivingChoiceType)(int32_t)vals[K_ACH_TYPE];
        choice->pCar = car_of((int32_t)vals[K_ACH_CAR]);
        choice->UseExtraLateralDistance = (int32_t)vals[K_ACH_EXTRA];
    }
    if (m & W_SECS)
        *secs = fbits(vals[K_SECS]);
    if (m & W_OKAY)
        *okay = (int)(int32_t)vals[K_OKAY];
    if (m & W_USED)
        *usedPreferred = (int)(int32_t)vals[K_USED];
    return r;
}

int32_t aipullover_calculate_score(DrivingInformation *info)
{
    return score(S_PULLOVER, "pullover", info, "");
}

int32_t aijustdrive_calculate_score(DrivingInformation *info)
{
    return score(S_DRIVE, "drive", info, "");
}

// ------------------------------------------------------ the constructors

// Each prints its arguments; and, as the real ones do, gives the action
// its table and stores its score, here plus the script's bias.
static void new_line(const char *name, AIAction *a, int32_t s, float t,
                     const char *extra)
{
    printf("  new %s %s %d %08x%s\n", name, lab(a), s, bitsf(t), extra);
    a->Base._vtable = FAKE_ACTION_VT;
    a->Score = s + (int32_t)vals[K_BIAS];
}

AIActionJustDrive *aijustdrive_init(AIActionJustDrive *a, int32_t score_,
                                    float timeout)
{
    new_line("drive", &a->Base, score_, timeout, "");
    return a;
}

AIActionPullOver *aipullover_init(AIActionPullOver *a, int32_t score_,
                                  float timeout, float pullOverTimeout,
                                  NearbyCarList *list, DrivingLocation *lc)
{
    char b[100];

    snprintf(b, sizeof b, " %08x %s %s", bitsf(pullOverTimeout), lab(list),
             lab(lc));
    new_line("pullover", &a->Base, score_, timeout, b);
    return a;
}

AIActionGetUnstuck *aigetunstuck_init(AIActionGetUnstuck *a, int32_t score_,
                                      float timeout, float minLifetime)
{
    char b[40];

    snprintf(b, sizeof b, " %08x", bitsf(minLifetime));
    new_line("unstuck", &a->Base, score_, timeout, b);
    return a;
}

AIActionAccidentRecovery *aiaccidentrecovery_init(AIActionAccidentRecovery *a,
                                                  int32_t score_,
                                                  float timeout)
{
    new_line("recovery", &a->Base, score_, timeout, "");
    return a;
}

AIActionIJustGotHit *aijustgothit_init(AIActionIJustGotHit *a, int32_t score_,
                                       float timeout, Car *cr)
{
    char b[60];

    snprintf(b, sizeof b, " %s", lab(cr));
    new_line("hit", &a->Base, score_, timeout, b);
    return a;
}

AIActionAvoidCars *aiavoidcars_init(AIActionAvoidCars *a, int32_t score_,
                                    float timeout, Car *cr, float secs,
                                    int okay, int usedPreferred)
{
    char b[100];

    snprintf(b, sizeof b, " %s %08x %d %d", lab(cr), bitsf(secs), okay,
             usedPreferred);
    new_line("avoid", &a->Base, score_, timeout, b);
    return a;
}

// ------------------------------------------------------------- the script

static int32_t *words_in;
static size_t   nwords_in, rd;

static int32_t next(void)
{
    if (rd >= nwords_in) {
        fprintf(stderr, "script overrun\n");
        exit(2);
    }
    return words_in[rd++];
}

static char **read_strings(int32_t *count)
{
    int32_t n = next(), i, k;
    char  **out = malloc(sizeof(char *) * (size_t)(n > 0 ? n : 1));

    for (i = 0; i < n; i++) {
        int32_t len = next();
        out[i] = malloc((size_t)len + 1);
        for (k = 0; k < len; k++)
            out[i][k] = (char)next();
        out[i][len] = 0;
    }
    *count = n;
    return out;
}

static AIAction *cur(void)
{
    if (d->Base.CurrentAction == NULL) {
        fprintf(stderr, "no current action\n");
        exit(2);
    }
    return d->Base.CurrentAction;
}

static void poke(int32_t f, int32_t v)
{
    uint32_t u = (uint32_t)v;

    switch (f) {
    case P_TIMER:       WorldTimer = v; break;
    case P_LOOP:        WorldLoopCounter = v; break;
    case P_LAST:        d->Base.LastTimeNonGetUnstuckActionWasCalled.PackedTime = u; break;
    case P_SECS:        d->Base.SecondsBeforeNextActionEvaluation = fbits(u); break;
    case P_PICK:        d->PickLowNumberedRoutes = v; break;
    case P_DTYPE:       drv.TheDriverType = (DriverType)v; break;
    case P_CARIDX:      car.CarIndex = (int16_t)v; break;
    case P_DRVNUM:      car.DriverNumber = (int16_t)v; break;
    case P_MODE:        car.TheMovementMode = (MovementMode)v; break;
    case P_LOCSEL:
        d->Base.CurrentDrivingLocation = v == 1 ? &loc : myloc();
        d->Base.CurrentDrivingChoice = &choice_obj;
        break;
    case P_LIST:
        d->Base.CurrentNearbyCarList =
            v ? (NearbyCarList *)(void *)list_mem : NULL;
        break;
    case P_CHOICE_TYPE: choice_obj.Type = (DrivingChoiceType)v; break;
    case P_CAMCAR:      CameraFollowThisCarInstead = v; break;
    case P_CAMDEF:      CameraFollowDefaultCar = v; break;
    case P_LOOKAHEAD:   AIDriverSecondsToLookAhead = fbits(u); break;
    case P_FORCE:       d->Base.ForceCurrentAction = (AIActionType)v; break;
    case P_CUR_TYPE:    cur()->Type = (AIActionType)v; break;
    case P_CUR_SCORE:   cur()->Score = v; break;
    case P_CUR_STATUS:  cur()->Base.Status = (PlanStatus)v; break;
    case P_CUR_CANEXP:  cur()->Base.CanExpire = v; break;
    default:
        fprintf(stderr, "no poke %d\n", f);
        exit(2);
    }
}

static void global(int32_t i, int32_t v)
{
    float f = fbits((uint32_t)v);

    switch (i) {
    case 0: AIActionJustDriveScore = v; break;
    case 1: AIActionAvoidCarsScore = v; break;
    case 2: AIActionIJustGotHitScore = v; break;
    case 3: AIActionGetUnstuckScore = v; break;
    case 4: AIActionAccidentRecoveryScore = v; break;
    case 5: AIActionPullOverScore = v; break;
    case 6: AIActionGetUnstuckLifetime = f; break;
    case 7: AIActionAvoidCarsLifetime = f; break;
    case 8: AIActionIJustGotHitLifetime = f; break;
    case 9: AIActionPullOverTrafficCarTimeout = f; break;
    default:
        fprintf(stderr, "no global %d\n", i);
        exit(2);
    }
}

// ------------------------------------------------------------- the dump

static const char *vtname(uint32_t v)
{
    static char b[16];

    if (v == TRAFFICDRIVER_VTABLE)
        return "trafficdriver";
    if (v == AICC_RETAIL_VT)
        return "aicc";
    if (v == FAKE_ACTION_VT)
        return "fav";
    snprintf(b, sizeof b, "%08x", v);
    return b;
}

// The point only on a route: a sign's route not loaded has retail's point
// 1064 + 112 x its NewPoint off NULL, the port's NULL, and nothing reads it.
static void dump_loc(const char *name, const DrivingLocation *l)
{
    printf("  %s %s %s %d %08x\n", name, lab(l->pRoute),
           l->pRoute != NULL ? lab(l->pRoutePoint) : "-",
           l->DrivingLine, l->LastRelaxedDrivingLineSwitchTime.PackedTime);
}

static void dump(void)
{
    const AIAction *a = d->Base.CurrentAction;
    const char *al = lab(a);

    printf("d vt %s car %s drv %s act %s force %d pick %d secs %08x "
           "last %08x\n",
           vtname(d->Base.Base._vtable), lab(d->Base.Base.pCar),
           lab(d->Base.Base.Driver), al, (int32_t)d->Base.ForceCurrentAction,
           d->PickLowNumberedRoutes,
           bitsf(d->Base.SecondsBeforeNextActionEvaluation),
           d->Base.LastTimeNonGetUnstuckActionWasCalled.PackedTime);
    printf("d choice %s mode %d\n",
           choice_str(&d->Base.MyCurrentDrivingInformation.MyDrivingChoice),
           (int32_t)car.TheMovementMode);
    dump_loc("loc", &loc);
    dump_loc("myloc", myloc());
    if (al[0] == 'a' || strcmp(al, "cur") == 0)
        printf("  act vt %s type %d score %d status %d exp %d\n",
               vtname(a->Base._vtable), (int32_t)a->Type, a->Score,
               (int32_t)a->Base.Status, a->Base.CanExpire);
}

// The functions the table may hold, by retail's addresses.
static uint32_t retail_addr(VtFn fn)
{
    static const struct {
        VtFn     fn;
        uint32_t addr;
    } map[] = {
        { (VtFn)trafficdriver_destroy, 0x0018c418u },
        { (VtFn)aicarcontroller_debug_display, 0x00191138u },
        { (VtFn)trafficdriver_do_snapshot, 0x0018c478u },
        { (VtFn)trafficdriver_think, 0x0018c4d8u },
        { (VtFn)aicarcontroller_set_current_route, 0x00190670u },
        { (VtFn)aicarcontroller_get_current_route, 0x00190708u },
        { (VtFn)aicarcontroller_get_current_route_point, 0x00190760u },
        { (VtFn)aicarcontroller_get_amount_out_of_bounds, 0x001907b8u },
        { (VtFn)aicarcontroller_find_where_i_am, 0x00192f10u },
        { (VtFn)trafficdriver_just_reset, 0x0018cb10u },
        { (VtFn)aicarcontroller_set_to_physics_mode, 0x00193650u },
        { (VtFn)aicarcontroller_force_boost, 0x00193758u },
        { (VtFn)aicarcontroller_release_boost, 0x00193780u },
        { (VtFn)trafficdriver_get_route_numbers_to_use, 0x0018cae8u },
        { (VtFn)aicarcontroller_choose_new_action, 0x00192780u },
        { (VtFn)aicarcontroller_generate_points_to_fulfill_action,
          0x00192668u },
    };
    size_t k;

    if (fn == NULL)
        return 0;
    for (k = 0; k < sizeof map / sizeof map[0]; k++)
        if (map[k].fn == fn)
            return map[k].addr;
    return 0xffffffffu;
}

static void dump_static(void)
{
    const VtEntry *t;
    int n, k;

    printf("g scores %d %d %d %d %d %d\n", AIActionJustDriveScore,
           AIActionAvoidCarsScore, AIActionIJustGotHitScore,
           AIActionGetUnstuckScore, AIActionAccidentRecoveryScore,
           AIActionPullOverScore);
    printf("g lifetimes %08x %08x %08x timeout %08x look %08x cam %d %d\n",
           bitsf(AIActionGetUnstuckLifetime),
           bitsf(AIActionAvoidCarsLifetime),
           bitsf(AIActionIJustGotHitLifetime),
           bitsf(AIActionPullOverTrafficCarTimeout),
           bitsf(AIDriverSecondsToLookAhead), CameraFollowDefaultCar,
           CameraFollowThisCarInstead);
    t = vt_table(TRAFFICDRIVER_VTABLE, &n);
    for (k = 0; k < 17; k++) {
        if (k < n)
            printf("vt %d %d %08x\n", k, t[k].delta, retail_addr(t[k].fn));
        else
            printf("vt %d - -\n", k);
    }
}

// ------------------------------------------------------------- the table

typedef void (*IntFn)(void *self, int32_t i);
typedef void (*FloatFn)(void *self, float f);
typedef void (*VoidFn)(void *self);
typedef void (*RoutesFn)(void *self, int32_t *first, int32_t *last);

static const VtEntry *slot(int s)
{
    return vt_slot(d->Base.Base._vtable, s);
}

#define SELF(e) vt_this(d, e)

// ------------------------------------------------------------- the main

int main(int argc, char **argv)
{
    FILE   *fp;
    long    len;
    int32_t ntags, nflat;
    char  **tags;
    size_t  end;
    int     k;

    if (argc != 2) {
        fprintf(stderr, "usage: trafficdriver_test ops.bin\n");
        return 2;
    }
    fp = fopen(argv[1], "rb");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    fseek(fp, 0, SEEK_END);
    len = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    words_in = malloc((size_t)len);
    nwords_in = (size_t)len / 4;
    if (fread(words_in, 4, nwords_in, fp) != nwords_in) {
        fprintf(stderr, "short read\n");
        return 2;
    }
    fclose(fp);

    tags = read_strings(&ntags);
    nflat = next();
    end = rd + (size_t)nflat;

    bSetMemoryHooks(malloc_hook, free_hook);
    vt_reset();
    trafficdriver_install_vtables();
    vt_install(FAKE_DRIVER_VT, fake_driver_vt, 9);
    vt_install(FAKE_ACTION_VT, fake_action_vt, 4);

    car.MyDriver = &drv;
    pCurrentWorld = &world;
    SignpostArray = signs;
    for (k = 0; k < NROUTES; k++)
        TheTrackRouteManager.pTrackRoutes[k] = &routes[k];
    cur_mem.a.Base._vtable = FAKE_ACTION_VT;

    while (rd < end) {
        int32_t op = next();

        switch (op) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_JUNK:
            memset(&du, next() & 0xff, sizeof du);
            break;
        case OP_NEW: {
            CarController *r;
            nslots = 0;             // each driver's actions from a0
            printf("new\n");
            r = trafficdriver_construct(d, &car);
            printf("new -> %s\n", lab(r));
            break;
        }
        case OP_DEL: {
            int32_t flags = next();
            const VtEntry *e = slot(CARCONTROLLER_VT_DTOR);
            printf("del %d\n", flags);
            ((IntFn)e->fn)(SELF(e), flags);
            break;
        }
        case OP_NULL:
            d->Base.Base.Driver = NULL;
            break;
        case OP_RAWDEL: {
            int32_t flags = next();
            d->Base.Base._vtable = AICC_RETAIL_VT;
            printf("rawdel %d\n", flags);
            trafficdriver_destroy(d, flags);
            break;
        }
        case OP_THINK: {
            float dt = fbits((uint32_t)next());
            const VtEntry *e = slot(CARCONTROLLER_VT_THINK);
            printf("think %08x\n", bitsf(dt));
            ((FloatFn)e->fn)(SELF(e), dt);
            break;
        }
        case OP_ROUTES: {
            int32_t r[2] = { 0x5a5a5a5a, 0x5a5a5a5a };
            const VtEntry *e = slot(112);
            ((RoutesFn)e->fn)(SELF(e), &r[0], &r[1]);
            printf("routes -> %d %d\n", r[0], r[1]);
            break;
        }
        case OP_RESET: {
            const VtEntry *e = slot(80);
            printf("reset\n");
            ((VoidFn)e->fn)(SELF(e));
            break;
        }
        case OP_EXEC:
            printf("exec\n");
            trafficdriver_execute_current_action(d);
            break;
        case OP_SPEED: {
            float s[3];
            memset(s, 0x5a, sizeof s);
            trafficdriver_calculate_desired_speed(d, &s[0], &s[1], &s[2]);
            printf("speed -> %08x %08x %08x\n", bitsf(s[0]), bitsf(s[1]),
                   bitsf(s[2]));
            break;
        }
        case OP_DIR:
            trafficdriver_set_direction(d, next());
            break;
        case OP_SET: {
            int32_t key = next(), v = next();
            if (key < 0 || key >= K_COUNT) {
                fprintf(stderr, "no key %d\n", key);
                return 2;
            }
            vals[key] = (uint32_t)v;
            break;
        }
        case OP_CUR: {
            int32_t present = next();
            d->Base.CurrentAction = present ? &cur_mem.a : NULL;
            break;
        }
        case OP_POKE: {
            int32_t f = next(), v = next();
            poke(f, v);
            break;
        }
        case OP_GLOBAL: {
            int32_t i = next(), v = next();
            global(i, v);
            break;
        }
        case OP_PT: {
            int32_t i = next(), x = next(), y = next();
            if (i < 0 || i >= NPTS) {
                fprintf(stderr, "no point %d\n", i);
                return 2;
            }
            pts[i][0] = fbits((uint32_t)x);
            pts[i][1] = fbits((uint32_t)y);
            break;
        }
        case OP_FILL:
            fill(cur());
            break;
        case OP_ROUTE: {
            TrackRoute *r = route_of(next());
            r->NumPoints = next();
            r->RouteNumber = (int16_t)next();
            break;
        }
        case OP_RPOINT: {
            TrackRoute *r = route_of(next());
            int32_t i = next(), lenb = next(), sign = next();
            TrackRoutePoint *p = &r->TrackRoutePointTable[i];
            p->Length = fbits((uint32_t)lenb);
            p->Bits = (p->Bits & ~TRP_SIGN_MASK) | ((uint32_t)sign & 0xffu);
            break;
        }
        case OP_SIGN: {
            int32_t i = next(), flags = next(), where = next();
            if (i < 0 || i >= NSIGNS) {
                fprintf(stderr, "no sign %d\n", i);
                return 2;
            }
            signs[i].Flags = (uint8_t)flags;
            signs[i].NewRoute = (uint8_t)(where & 0xff);
            signs[i].NewPoint = (uint16_t)((uint32_t)where >> 8);
            break;
        }
        case OP_LOC: {
            int32_t which = next(), rk = next(), pi = next(), line = next(),
                    sw = next();
            DrivingLocation *l = which == 1 ? &loc : myloc();
            l->pRoute = route_of(rk);
            l->pRoutePoint = rk >= 0 ? &routes[rk].TrackRoutePointTable[pi]
                                     : NULL;
            l->DrivingLine = line;
            l->LastRelaxedDrivingLineSwitchTime.PackedTime = (uint32_t)sw;
            break;
        }
        case OP_WORLD:
            world.TotalNumCars = next();
            world.TrafficCarPos = next();
            break;
        case OP_TABLE: {
            int32_t i = next(), c = next();
            if (i < 0 || i >= WORLD_MAX_CARS) {
                fprintf(stderr, "no table slot %d\n", i);
                return 2;
            }
            world.CarTable[i] = car_of(c);
            break;
        }
        case OP_DUMP:
            dump();
            break;
        case OP_STATIC:
            dump_static();
            break;
        default:
            fprintf(stderr, "op %d\n", op);
            return 2;
        }
    }
    return 0;
}
