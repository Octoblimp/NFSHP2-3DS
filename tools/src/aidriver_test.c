// Harness for tools/aidriver_check.py: runs the checker's op script on the
// port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out, and stands in for what the checker stubs.
//
//     aidriver_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "aiactions.h"
#include "aicarcontroller.h"
#include "aidriver.h"
#include "average.h"
#include "bmem.h"
#include "car.h"
#include "cardriver.h"
#include "copmanager.h"
#include "difficultyinfo.h"
#include "drivingchoice.h"
#include "nearbycar.h"
#include "psychodriver.h"
#include "race.h"
#include "realtime.h"
#include "timer.h"
#include "trackpath.h"
#include "vtable.h"
#include "world.h"

enum {
    OP_TAG, OP_JUNK, OP_NEW, OP_DEL, OP_NULL, OP_THINK, OP_ROUTES, OP_AVOID,
    OP_CHOOSE, OP_SET, OP_CUR, OP_POKE, OP_DIFF, OP_DUMP, OP_STATIC,
    OP_RAWDEL
};

enum {
    K_RANDOM, K_RCLEAR, K_OOB, K_MASK, K_RB, K_HIT, K_AVOIDCAR, K_SECS,
    K_OKAY, K_USED, K_ACH_TYPE, K_ACH_CAR, K_ACH_EXTRA, K_PASSCAR,
    K_PCH_TYPE, K_PCH_CAR, K_PCH_EXTRA, K_AMOUNT, K_SCORE,
    K_COUNT = K_SCORE + 7
};

enum {
    S_UNSTUCK, S_ROADBLOCK, S_HIT, S_AVOID, S_RECOVERY, S_PASS, S_DRIVE
};

enum {
    W_RB = 1 << 0, W_HIT = 1 << 1, W_AVOIDCAR = 1 << 2, W_SECS = 1 << 3,
    W_OKAY = 1 << 4, W_USED = 1 << 5, W_ACH = 1 << 6, W_PASSCAR = 1 << 7,
    W_PCH = 1 << 8, W_AMOUNT = 1 << 9
};

enum {
    P_TIMER, P_LAST, P_POT, P_NOTAVOID, P_NOTAVOID_T, P_PROGRESS_T,
    P_TRACKLEN, P_LAPRATE, P_SKILL, P_AVG_SAMPLES, P_AVG_AVERAGE, P_AVG_SLOT,
    P_LIST, P_LOC, P_JDSCORE
};

#define NO_CAR   (-1)
#define NCARS    8
#define MY_CAR   NCARS
#define NSLOTS   64
#define SLACK    16
#define MAX_HEAP 16384
#define QUEUE    64

// AICarController's retail table, which the stand-in constructor stores,
// and the test driver table PsychoDriver's stand-in gives the driver.
#define AICC_RETAIL_VT  0x002b4d90u
#define FAKE_DRIVER_VT  0x01e0a000u

// ------------------------------------------------------------- the world

static union {
    AIDriver      d;
    unsigned char b[sizeof(AIDriver)];
} du;
static AIDriver *const d = &du.d;

static Car        car;
static DriverInfo drv;
static RacingCar  rc;
static char       cars[NCARS][16];
static char       world_mem[16];
static char       list_mem[16];
static char       loc_mem[16];
static char       rb_mem[16];
static AIAction   cur_act;
static AIAction   old_act;
static union {
    AIAction a;
    double   align;
    char     b[1024];
} slot_mem[NSLOTS];
static int nslots;

// What the linked files leave to the game.
int32_t          WorldTimer;
World           *pCurrentWorld;
TrackPathManager TheTrackPathManager;
int32_t          AIActionJustDriveScore;

static uint32_t vals[K_COUNT];
static uint32_t queue[QUEUE];
static int      nqueue;

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

// ------------------------------------------------------------- the heap

static struct {
    const void *p;
    size_t      span;
} heap[MAX_HEAP];
static int nheap;

// The console's size of what the port asked for: its PsychoDriver and its
// Average record are wider on a 64-bit host.
static int console_size(int size, const char *name)
{
    if (strcmp(name, "PsychoDriver") == 0 && size == (int)sizeof(PsychoDriver))
        return 624;
    if (strcmp(name, "Very Stuck Progress Average") == 0
        && size == (int)sizeof(Average))
        return 16;
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
        { &car, "car" },
        { world_mem, "world" },
        { list_mem, "list" },
        { loc_mem, "loc" },
        { &cur_act, "cur" },
        { &old_act, "old" },
        { rb_mem, "rb" },
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
    for (i = 0; i < NSLOTS; i++)
        if (a == (const void *)&slot_mem[i]) {
            snprintf(buf, n, "a%d", i);
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

void aicarcontroller_think(AICarController *c, float dt)
{
    printf("  aicc think %s %08x\n", lab(c), bitsf(dt));
}

void aicarcontroller_maybe_honk_and_or_blink_headlights(AICarController *c,
                                                        Car *cr,
                                                        NearbyCarList *list)
{
    printf("  honk %s %s %s\n", lab(c), lab(cr), lab(list));
}

float aicarcontroller_get_amount_out_of_bounds(AICarController *c)
{
    printf("  oob %s -> %08x\n", lab(c), vals[K_OOB]);
    return fbits(vals[K_OOB]);
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

void aicarcontroller_find_where_i_am(AICarController *c)
{
    (void)c;
    never("find_where_i_am");
}

void aicarcontroller_just_reset(AICarController *c)
{
    (void)c;
    never("just_reset");
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

void aicarcontroller_generate_points_to_fulfill_action(AICarController *c,
                                                       AIAction *a)
{
    (void)c; (void)a;
    never("generate_points_to_fulfill_action");
}

static void fake_driver_dtor(void *self, int32_t flags)
{
    printf("  driver dtor %s %d\n", lab(self), flags);
}

static const VtEntry fake_driver_vt[2] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)fake_driver_dtor },
};

PsychoDriver *psychodriver_init(PsychoDriver *pd, Car *cr)
{
    printf("  psycho init %s %s\n", lab(pd), lab(cr));
    pd->Base._vtable = FAKE_DRIVER_VT;
    return pd;
}

void car_set_friction_boost(Car *c, float f)
{
    printf("  friction %s %08x\n", lab(c), bitsf(f));
}

float world_random_f(World *w, float f)
{
    uint32_t r = 0;
    int k;

    if (nqueue > 0) {
        r = queue[0];
        for (k = 1; k < nqueue; k++)
            queue[k - 1] = queue[k];
        nqueue--;
    }
    printf("  random %s %08x -> %08x\n", lab(w), bitsf(f), r);
    return fbits(r);
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

static void put_choice(DrivingChoice *c, int base)
{
    c->Type = (DrivingChoiceType)(int32_t)vals[base];
    c->pCar = car_of((int32_t)vals[base + 1]);
    c->UseExtraLateralDistance = (int32_t)vals[base + 2];
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

int32_t aiavoidroadblock_calculate_score(DrivingInformation *info,
                                         const tRoadBlock **rb)
{
    char b[64];
    int32_t r;

    snprintf(b, sizeof b, " rb %s", lab(*rb));
    r = score(S_ROADBLOCK, "roadblock", info, b);
    if (vals[K_MASK] & W_RB)
        *rb = (int32_t)vals[K_RB] >= 0 ? (const tRoadBlock *)(void *)rb_mem
                                       : NULL;
    return r;
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
    if (m & W_ACH)
        put_choice(choice, K_ACH_TYPE);
    if (m & W_SECS)
        *secs = fbits(vals[K_SECS]);
    if (m & W_OKAY)
        *okay = (int)(int32_t)vals[K_OKAY];
    if (m & W_USED)
        *usedPreferred = (int)(int32_t)vals[K_USED];
    return r;
}

int32_t aiaccidentrecovery_calculate_score(DrivingInformation *info)
{
    return score(S_RECOVERY, "recovery", info, "");
}

int32_t aipass_calculate_score(DrivingInformation *info, Car **cr,
                               DrivingChoice *choice, float *amount)
{
    char b[200];
    uint32_t m = vals[K_MASK];
    int32_t r;

    snprintf(b, sizeof b, " car %s choice %s amount %08x", lab(*cr),
             choice_str(choice), bitsf(*amount));
    r = score(S_PASS, "pass", info, b);
    if (m & W_PASSCAR)
        *cr = car_of((int32_t)vals[K_PASSCAR]);
    if (m & W_PCH)
        put_choice(choice, K_PCH_TYPE);
    if (m & W_AMOUNT)
        *amount = fbits(vals[K_AMOUNT]);
    return r;
}

int32_t aijustdrive_calculate_score(DrivingInformation *info)
{
    return score(S_DRIVE, "drive", info, "");
}

// ------------------------------------------------------ the constructors

static void new_line(const char *name, const void *a, int32_t s, float t,
                     const char *extra)
{
    printf("  new %s %s %d %08x%s\n", name, lab(a), s, bitsf(t), extra);
}

AIActionJustDrive *aijustdrive_init(AIActionJustDrive *a, int32_t score_,
                                    float timeout)
{
    new_line("drive", a, score_, timeout, "");
    return a;
}

AIActionDraft *aidraft_init(AIActionDraft *a, int32_t score_, float timeout)
{
    new_line("draft", a, score_, timeout, "");
    return a;
}

AIActionPullOver *aipullover_init(AIActionPullOver *a, int32_t score_,
                                  float timeout, float pullOverTimeout,
                                  NearbyCarList *list, DrivingLocation *loc)
{
    char b[100];

    snprintf(b, sizeof b, " %08x %s %s", bitsf(pullOverTimeout), lab(list),
             lab(loc));
    new_line("pullover", a, score_, timeout, b);
    return a;
}

AIActionGetUnstuck *aigetunstuck_init(AIActionGetUnstuck *a, int32_t score_,
                                      float timeout, float minLifetime)
{
    char b[40];

    snprintf(b, sizeof b, " %08x", bitsf(minLifetime));
    new_line("unstuck", a, score_, timeout, b);
    return a;
}

AIActionAccidentRecovery *aiaccidentrecovery_init(AIActionAccidentRecovery *a,
                                                  int32_t score_,
                                                  float timeout)
{
    new_line("recovery", a, score_, timeout, "");
    return a;
}

AIActionAvoidRoadBlock *aiavoidroadblock_init(AIActionAvoidRoadBlock *a,
                                              int32_t score_, float timeout,
                                              const tRoadBlock *rb)
{
    char b[60];

    snprintf(b, sizeof b, " %s", lab(rb));
    new_line("roadblock", a, score_, timeout, b);
    return a;
}

AIActionIJustGotHit *aijustgothit_init(AIActionIJustGotHit *a, int32_t score_,
                                       float timeout, Car *cr)
{
    char b[60];

    snprintf(b, sizeof b, " %s", lab(cr));
    new_line("hit", a, score_, timeout, b);
    return a;
}

AIActionAvoidCars *aiavoidcars_init(AIActionAvoidCars *a, int32_t score_,
                                    float timeout, Car *cr, float secs,
                                    int okay, int usedPreferred)
{
    char b[100];

    snprintf(b, sizeof b, " %s %08x %d %d", lab(cr), bitsf(secs), okay,
             usedPreferred);
    new_line("avoid", a, score_, timeout, b);
    return a;
}

AIActionPass *aipass_init(AIActionPass *a, int32_t score_, float timeout,
                          Car *cr, float amount)
{
    char b[100];

    snprintf(b, sizeof b, " %s %08x", lab(cr), bitsf(amount));
    new_line("pass", a, score_, timeout, b);
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

static void poke(int32_t f, int32_t v)
{
    uint32_t u = (uint32_t)v;
    Average *a = d->pVeryStuckProgress;

    switch (f) {
    case P_TIMER:       WorldTimer = v; break;
    case P_LAST:        d->Base.LastTimeNonGetUnstuckActionWasCalled.PackedTime = u; break;
    case P_POT:         d->Base.PullOverTimeout = fbits(u); break;
    case P_NOTAVOID:    d->CarToPurposefullyNotAvoid = car_of(v); break;
    case P_NOTAVOID_T:  d->StartTimeForPurposefullyNotAvoidingCar.PackedTime = u; break;
    case P_PROGRESS_T:  d->VeryStuckProgressTimer.PackedTime = u; break;
    case P_TRACKLEN:    TheTrackPathManager.TrackLength = fbits(u); break;
    case P_LAPRATE:     rc.dCurrentLapNumberExact = fbits(u); break;
    case P_SKILL:       drv.SkillLevel = (int8_t)v; break;
    case P_AVG_SAMPLES: a->nSamples = (uint8_t)v; break;
    case P_AVG_AVERAGE: a->fAverage = fbits(u); break;
    case P_AVG_SLOT:    a->nCurrentSlot = (uint8_t)v; break;
    case P_LIST:
        d->Base.CurrentNearbyCarList =
            v ? (NearbyCarList *)(void *)list_mem : NULL;
        break;
    case P_LOC:
        d->Base.CurrentDrivingLocation =
            v ? (DrivingLocation *)(void *)loc_mem : NULL;
        break;
    case P_JDSCORE:     AIActionJustDriveScore = v; break;
    default:
        fprintf(stderr, "no poke %d\n", f);
        exit(2);
    }
}

// ------------------------------------------------------------- the dump

static const char *vtname(uint32_t v)
{
    static char b[16];

    if (v == AIDRIVER_VTABLE)
        return "aidriver";
    if (v == AICC_RETAIL_VT)
        return "aicc";
    snprintf(b, sizeof b, "%08x", v);
    return b;
}

static void dump(void)
{
    const Average *a = d->pVeryStuckProgress;
    const char *al = lab(a);

    printf("d vt %s car %s drv %s act %s skip %s skipt %08x prog %08x "
           "avg %s\n",
           vtname(d->Base.Base._vtable), lab(d->Base.Base.pCar),
           lab(d->Base.Base.Driver), lab(d->Base.CurrentAction),
           lab(d->CarToPurposefullyNotAvoid),
           d->StartTimeForPurposefullyNotAvoidingCar.PackedTime,
           d->VeryStuckProgressTimer.PackedTime, al);
    printf("d last %08x pot %08x choice %s\n",
           d->Base.LastTimeNonGetUnstuckActionWasCalled.PackedTime,
           bitsf(d->Base.PullOverTimeout),
           choice_str(&d->Base.MyCurrentDrivingInformation.MyDrivingChoice));
    if (strcmp(al, "null") != 0 && strcmp(al, "?") != 0) {
        char b[600];
        size_t at = 0;
        int k;

        b[0] = 0;
        for (k = 0; k < a->nSlots; k++)
            at += (size_t)snprintf(b + at, sizeof b - at, k ? " %08x" : "%08x",
                                   bitsf(a->pData[k]));
        printf("  avg %d %d %d %08x %08x %s\n", a->nSlots, a->nCurrentSlot,
               a->nSamples, bitsf(a->fTotal), bitsf(a->fAverage), b);
    }
}

// The functions the table may hold, by retail's addresses.
static uint32_t retail_addr(VtFn fn)
{
    static const struct {
        VtFn     fn;
        uint32_t addr;
    } map[] = {
        { (VtFn)aidriver_destroy, 0x00130090u },
        { (VtFn)aicarcontroller_debug_display, 0x00191138u },
        { (VtFn)aidriver_think, 0x00130188u },
        { (VtFn)aicarcontroller_set_current_route, 0x00190670u },
        { (VtFn)aicarcontroller_get_current_route, 0x00190708u },
        { (VtFn)aicarcontroller_get_current_route_point, 0x00190760u },
        { (VtFn)aicarcontroller_get_amount_out_of_bounds, 0x001907b8u },
        { (VtFn)aicarcontroller_find_where_i_am, 0x00192f10u },
        { (VtFn)aicarcontroller_just_reset, 0x00190850u },
        { (VtFn)aicarcontroller_set_to_physics_mode, 0x00193650u },
        { (VtFn)aicarcontroller_force_boost, 0x00193758u },
        { (VtFn)aicarcontroller_release_boost, 0x00193780u },
        { (VtFn)aidriver_get_route_numbers_to_use, 0x00130890u },
        { (VtFn)aidriver_choose_new_action, 0x00130238u },
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
    const int32_t scores[10] = {
        AIActionDraftScore, AIActionPassScore, AIActionNudgeCarScore,
        AIActionBlockScore, AIActionAvoidCarsScore, AIActionIJustGotHitScore,
        AIActionGetUnstuckScore, AIActionAccidentRecoveryScore,
        AIActionPullOverScore, AIActionAvoidRoadBlockScore,
    };
    const float lifetimes[10] = {
        AIActionPassLifetime, AIActionDraftLifetime, AIActionNudgeCarLifetime,
        AIActionJustDriveLifetime, AIActionBlockLifetime,
        AIActionGetUnstuckLifetime, AIActionPullOverLifetime,
        AIActionAvoidCarsLifetime, AIActionIJustGotHitLifetime,
        AIActionAccidentRecoveryLifetime,
    };
    const VtEntry *t;
    int n, k;

    printf("g scores");
    for (k = 0; k < 10; k++)
        printf(" %d", scores[k]);
    printf("\ng lifetimes");
    for (k = 0; k < 10; k++)
        printf(" %08x", bitsf(lifetimes[k]));
    printf("\ng timeouts %08x %08x %08x friction %08x\n",
           bitsf(AIActionPullOverTrafficCarTimeout),
           bitsf(AIActionPullOverCrossFinishLineTimeout),
           bitsf(AIActionPullOverStoppedByCopsTimeout),
           bitsf(AIDriverFrictionBoost));
    t = vt_table(AIDRIVER_VTABLE, &n);
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
typedef void (*RoutesFn)(void *self, int32_t *first, int32_t *last);
typedef void (*ChooseFn)(void *self, AIAction **out, AIActionType type);

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

    if (argc != 2) {
        fprintf(stderr, "usage: aidriver_test ops.bin\n");
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
    aidriver_install_vtables();
    vt_install(FAKE_DRIVER_VT, fake_driver_vt, 2);

    car.MyDriver = &drv;
    car.pRacingCar = &rc;
    pCurrentWorld = (World *)(void *)world_mem;

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
            r = aidriver_construct(d, &car);
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
            if (next() == 0)
                d->Base.Base.Driver = NULL;
            else
                d->pVeryStuckProgress = NULL;
            break;
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
        case OP_AVOID: {
            Car *c = car_of(next());
            float secs = fbits((uint32_t)next());
            printf("avoid %s %08x\n", lab(c), bitsf(secs));
            printf("avoid -> %d\n",
                   aidriver_should_we_avoid_this_car(d, c, secs));
            break;
        }
        case OP_CHOOSE: {
            AIActionType type = (AIActionType)next();
            AIAction *out = &old_act;
            const VtEntry *e = slot(120);
            printf("choose %d\n", (int32_t)type);
            ((ChooseFn)e->fn)(SELF(e), &out, type);
            printf("choose -> %s\n", lab(out));
            break;
        }
        case OP_SET: {
            int32_t k = next(), v = next();
            if (k == K_RANDOM) {
                if (nqueue >= QUEUE) {
                    fprintf(stderr, "random queue full\n");
                    return 3;
                }
                queue[nqueue++] = (uint32_t)v;
            } else if (k == K_RCLEAR) {
                nqueue = 0;
            } else if (k >= 0 && k < K_COUNT) {
                vals[k] = (uint32_t)v;
            } else {
                fprintf(stderr, "no key %d\n", k);
                return 2;
            }
            break;
        }
        case OP_CUR: {
            int32_t present = next(), type = next(), sc = next();
            if (present) {
                cur_act.Type = (AIActionType)type;
                cur_act.Score = sc;
                d->Base.CurrentAction = &cur_act;
            } else {
                d->Base.CurrentAction = NULL;
            }
            break;
        }
        case OP_POKE: {
            int32_t f = next(), v = next();
            poke(f, v);
            break;
        }
        case OP_DIFF: {
            int32_t off = next(), v = next();
            if (off < 0 || (size_t)off + 4 > sizeof TheDifficultyInfo) {
                fprintf(stderr, "difficulty offset %d\n", off);
                return 2;
            }
            memcpy((char *)&TheDifficultyInfo + off, &v, 4);
            break;
        }
        case OP_DUMP:
            dump();
            break;
        case OP_STATIC:
            dump_static();
            break;
        case OP_RAWDEL: {
            int32_t flags = next();
            d->Base.Base._vtable = AICC_RETAIL_VT;
            printf("rawdel %d\n", flags);
            aidriver_destroy(d, flags);
            break;
        }
        default:
            fprintf(stderr, "op %d\n", op);
            return 2;
        }
    }
    return 0;
}
