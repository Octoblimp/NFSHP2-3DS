// Host harness for 3DS Files/source/aicarcontroller.c, the AI car
// controller (steps 11e-1 to 11e-4). Runs the op script tools/aicarcontroller_check.py
// writes and prints the transcript it diffs against the retail image, run
// in mipsemu over the same script.
//
// It is drivingchoice_test.c with more: drivingchoice_world.inc is
// included, so that harness's world (the cars, routes, signs, the list and
// the test tables) and its ops are this one's too. A controller under test
// is constructed in place of a car's own, in ctrls[]. On top of
// drivingchoice_test.c's stubs it stands in for bMalloc and bFree (through
// bmem.c's hooks: a block of 64 bytes each, named m0, m1, ...),
// Car::SetMovementMode (carmodes.c's), the drivers' SetSteerToPoint and
// ZeroSteeringMemory, a test controller table whose GetRouteNumbersToUse
// and ChooseNewAction answer the script, and fake actions whose destructor
// and CalculatePointsToDrive print, World::Random answering the script's
// queue and GetTrackInfo a TrackInfo of the script's, each printing a line
// as the checker's stubs do. drivingchoice_test.c's stand-in for the sign
// decision gives way to the port's SignPostDecision, as main.c's seam
// does. For 11e-3 it has full players (player.c's PlayerPlayersByNumber
// with them), each car's RacingCar, a race coordinator, playercam.c's
// SkipFE pointer and the drivers' GetDesiredSpeed, answering the script.
// For 11e-4 it stands in for the drivers' SetDesiredSpeed, SetTarget,
// StartHonkHorn, StopHonkHorn and IsHonking (the last answering the
// script), World::Random(int) from the same queue as the float's, and
// carcollisionbody.c's BoringAIForCameraTuningOn. For 11e-5 it stands in
// for BeltMover::SetBelt (carmodes.h's seam), Car::DebugSetPosition,
// DriveTargetRenderer::SetTargetToRender and the fake actions' three
// tests, answering the script, and has realtime.c's WorldLoopCounter.
//
// A float prints as its bits, every NaN as "nan", and a pointer by what it
// points at. The ops and every line's format are the checker's.
#include "drivingchoice_world.inc"

#include "average.h"
#include "bmath.h"
#include "bmem.h"
#include "carmodes.h"
#include "configitems.h"
#include "difficultyinfo.h"
#include "playercam.h"
#include "raceinit.h"

// raceinit.c's, as it starts.
int32_t nDefaultMovementMode = MELLOW_MOVEMENT;

// carmodes.c's, which would bring the movers with it.
void car_set_movement_mode(Car *c, MovementMode mode)
{
    printf("  mode %s %d\n", nm(c), (int)mode);
    c->TheMovementMode = mode;
}

// cardriver.c's, which only car_new_null_controller reaches.
void cardriver_init(CarDriver *d)
{
    (void)d;
    fprintf(stderr, "cardriver_init called\n");
    exit(2);
}

// The checker's addresses for the two test tables.
#define TVT 0x010c2100u
#define AVT 0x010c2200u

#define NHEAP  16
#define HEAP_BLOCK 64
#define NFACTS 8

static unsigned char heap[NHEAP][HEAP_BLOCK];
static int nheap;
static AIAction facts[NFACTS];
static int32_t fa_pt[NFACTS];
static int choose_q[16], nchoose, ichoose;
static int32_t rnum_first[NCARS], rnum_last[NCARS];
static VtEntry tvt[AICARCONTROLLER_VT_ENTRIES];
static VtEntry avt[AIACTION_VT_ENTRIES];
static TrackInfo tinfo;
#define NRANDOM 16
static float rq[NRANDOM];
static uint32_t rqw[NRANDOM];   // the same words, for World::Random(int)
static int nrq, irq;

// 11e-3's: each car's player and its speed ratio's Average, its RacingCar,
// the race coordinator (its state the first word), SkipFE's word and what
// each driver's GetDesiredSpeed answers.
static struct Player plr[NCARS];
static int plr_used[NCARS];
static Average pavg[NCARS];
static RacingCar rcars[NCARS];
static uint32_t rcoord[4];
static int skipfe;
static float gds[NCARS];

// player.c's and playercam.c's.
struct Player *PlayerPlayersByNumber[2];
const int *gPlayerCamSkipFE;

// 11e-4's: what each driver's IsHonking answers, and carcollisionbody.c's
// switch.
static int32_t ish[NCARS];
int32_t BoringAIForCameraTuningOn;

// 11e-5's: realtime.c's loop counter, carmodes.c's seam (below) and what
// each fake action's HasExpired, HasFailed and HasBeenAccomplished answer.
int32_t WorldLoopCounter;
static int32_t fa_test[NFACTS][3];

// ------------------------------------------------------------ the stubs

// Retail's Average is 16 bytes; the host's is 24 with an 8-byte pointer.
static void *malloc_hook(int size, const char *name, int flags, int pool)
{
    void *p;
    int shown = size;

    if (sizeof(void *) != 4 && size == (int)sizeof(Average))
        shown = 16;
    if (nheap >= NHEAP || size < 0 || size > HEAP_BLOCK) {
        fprintf(stderr, "bMalloc: %d bytes for %s\n", size, name);
        exit(2);
    }
    p = heap[nheap];
    printf("  alloc m%d size %d name %s flags %d pool %d\n", nheap, shown,
           name, flags, pool);
    nheap++;
    fill(p, HEAP_BLOCK);
    return p;
}

static void free_hook(void *p)
{
    printf("  free %s\n", nm(p));
}

static void fk_set_steer_to_point(void *self, bVector2 *p)
{
    printf("  sstp %s %s %s\n", nm(&cars[driver_index(self)]), fx(p->x),
           fx(p->y));
}

static void fk_zero_steering_memory(void *self)
{
    printf("  zsm %s\n", nm(&cars[driver_index(self)]));
}

static void fk_route_numbers(void *self, int32_t *first, int32_t *last)
{
    int i = ctrl_index(self);

    printf("  rnum %s\n", nm(&ctrls[i]));
    *first = rnum_first[i];
    *last = rnum_last[i];
}

static void fk_choose(void *self, AIAction **out, AIActionType type)
{
    int i = ichoose < nchoose ? choose_q[ichoose++] : -1;

    printf("  choose %s %d\n", nm(&ctrls[ctrl_index(self)]), (int)type);
    *out = i >= 0 ? &facts[i] : NULL;
}

static int fact_index(void *self)
{
    int i = index_in(self, facts, sizeof facts[0], NFACTS);

    if (i < 0) {
        fprintf(stderr, "an action that is not one of ours\n");
        exit(2);
    }
    return i;
}

static void fk_action_dtor(void *self, int32_t flags)
{
    printf("  adel %s %d\n", nm(self), (int)flags);
    (void)fact_index(self);
}

static void fk_action_points(void *self, DrivingInformation *i)
{
    int k = fact_index(self);

    printf("  acp %s %s\n", nm(self), nm(i));
    facts[k].PointsToDriveWillExecuteAction = fa_pt[k];
}

// worldstep.c's: the script's queue, then 0.
float world_random_f(World *w, float f)
{
    printf("  random %d %s\n", w == &world, fx(f));
    return irq < nrq ? rq[irq++] : 0.0f;
}

int32_t world_random_i(World *w, int32_t range)
{
    printf("  irandom %d %d\n", w == &world, (int)range);
    return irq < nrq ? (int32_t)rqw[irq++] : 0;
}

// track.c's, which would bring the track's loading with it.
TrackInfo *track_get_info(int i)
{
    printf("  tinfo %d\n", i);
    return &tinfo;
}

static float fk_get_desired_speed(void *self)
{
    int k = driver_index(self);

    printf("  gds %s\n", nm(&cars[k]));
    return gds[k];
}

static void fk_set_desired_speed(void *self, float speed, float time,
                                 float tol, int32_t allowed)
{
    printf("  sds %s %s %s %s %d\n", nm(&cars[driver_index(self)]),
           fx(speed), fx(time), fx(tol), (int)allowed);
}

// A target that is no one's is Think's own, on its stack: shown whole.
static void fk_set_target(void *self, const DriveTarget *t)
{
    const char *n = nm(t);

    if (n[0] != '?') {
        printf("  stg %s %s\n", nm(&cars[driver_index(self)]), n);
        return;
    }
    printf("  stg %s tmp\n", nm(&cars[driver_index(self)]));
    dump_target(t);
}

static void fk_start_honk(void *self)
{
    printf("  honkon %s\n", nm(&cars[driver_index(self)]));
}

static void fk_stop_honk(void *self)
{
    printf("  honkoff %s\n", nm(&cars[driver_index(self)]));
}

static int32_t fk_is_honking(void *self)
{
    int k = driver_index(self);

    printf("  ishonk %s\n", nm(&cars[k]));
    return ish[k];
}

// 11e-5's.
static void fk_set_belt(CarMover *m)
{
    printf("  setbelt %s\n", nm(m));
}

BeltMoverSetBeltFn gBeltMoverSetBeltFn = fk_set_belt;

// carreset.c's, which would bring the reset with it.
void car_debug_set_position(Car *c, const bVector3 *pos, float speed,
                            uint16_t angle)
{
    printf("  dsp %s %s %s %s %s %d\n", nm(c), fx(pos->x), fx(pos->y),
           fx(pos->z), fx(speed), (int)angle);
}

// drivetargetrenderer.c's, whose renderer drivingchoice_world.inc has.
void drivetargetrenderer_set_target_to_render(DriveTargetRenderer *r,
                                              DriveTarget *t)
{
    printf("  render %s %s\n", nm(r), nm(t));
}

static int fk_action_test(void *self, DrivingInformation *i, int which,
                          const char *tag)
{
    int k = fact_index(self);

    printf("  %s %s %s\n", tag, nm(self), nm(i));
    return fa_test[k][which];
}

static int fk_has_expired(void *self, DrivingInformation *i)
{
    return fk_action_test(self, i, 0, "ahe");
}

static int fk_has_failed(void *self, DrivingInformation *i)
{
    return fk_action_test(self, i, 1, "ahf");
}

static int fk_has_been_accomplished(void *self, DrivingInformation *i)
{
    return fk_action_test(self, i, 2, "ahba");
}

// ------------------------------------------------------------ the names

static const char *ac_nm(const void *p, char *b)
{
    int i, j;

    for (i = 0; i < NCARS; i++) {
        DrivingInformation *d = &ctrls[i].MyCurrentDrivingInformation;

        if (p == &d->MyNearbyCarList) {
            sprintf(b, "kn%d", i);
            return b;
        }
        if (p == &d->MyDrivingLocation) {
            sprintf(b, "kl%d", i);
            return b;
        }
        if (p == &d->MyDrivingChoice) {
            sprintf(b, "kc%d", i);
            return b;
        }
        j = index_in(p, d->MyNearbyCarList.Array, sizeof(NearbyCar),
                     NEARBYCARLIST_MAX);
        if (j >= 0) {
            sprintf(b, "ke%d:%d", i, j);
            return b;
        }
    }
    if ((i = index_in(p, heap, sizeof heap[0], NHEAP)) >= 0) {
        sprintf(b, "m%d", i);
        return b;
    }
    if ((i = index_in(p, cdrivers, sizeof cdrivers[0], NCARS)) >= 0) {
        sprintf(b, "d%d", i);
        return b;
    }
    if ((i = index_in(p, facts, sizeof facts[0], NFACTS)) >= 0) {
        sprintf(b, "fa%d", i);
        return b;
    }
    for (i = 0; i < NFACTS; i++)
        if (p == &facts[i].PointsToDrive) {
            sprintf(b, "pt%d", i);
            return b;
        }
    if ((i = index_in(p, plr, sizeof plr[0], NCARS)) >= 0) {
        sprintf(b, "P%d", i);
        return b;
    }
    return NULL;
}

static const char *ctl_vt_name(uint32_t v)
{
    static char b[16];

    switch (v) {
    case AICARCONTROLLER_VTABLE:
        return "vK";
    case TVT:
        return "vT";
    case CVT:
        return "vC";
    case CARCONTROLLER_VTABLE:
        return "vB";
    case AVT:
        return "vF";
    }
    sprintf(b, "%08x", (unsigned)v);
    return b;
}

static void ac_reset(void)
{
    nheap = 0;
    memset(facts, 0, sizeof facts);
    memset(fa_pt, 0, sizeof fa_pt);
    nchoose = ichoose = 0;
    memset(rnum_first, 0, sizeof rnum_first);
    memset(rnum_last, 0, sizeof rnum_last);
    nDefaultMovementMode = MELLOW_MOVEMENT;
    memset(&tinfo, 0, sizeof tinfo);
    tinfo.SignpostGracePeriod = -1;
    TheRaceParameters.TrackNumber = 0;
    memset(TheDifficultyInfo.AISkillLevel, 0,
           sizeof TheDifficultyInfo.AISkillLevel);
    nrq = irq = 0;
    gAISignPostDecisionFn = aicarcontroller_sign_post_decision;
    // 11e-3's: no players, RacingCars, catchup, SkipFE, race parameters,
    // difficulty or player positions; the coordinator in state 0.
    memset(plr, 0, sizeof plr);
    memset(plr_used, 0, sizeof plr_used);
    memset(pavg, 0, sizeof pavg);
    memset(rcars, 0, sizeof rcars);
    memset(rcoord, 0, sizeof rcoord);
    memset(gds, 0, sizeof gds);
    pRaceCoordinator = (RaceCoordinator *)(void *)rcoord;
    bBeltMover = 1;
    CarControllerDisableCatchup = 0;
    nLastGlueReason = 0;
    skipfe = 0;
    gPlayerCamSkipFE = &skipfe;
    SkipFEBeACop = 0;
    PlayerPlayersByNumber[0] = NULL;
    PlayerPlayersByNumber[1] = NULL;
    TheRaceParameters.NumPlayerCars = 0;
    TheRaceParameters.NumAICars = 0;
    TheRaceParameters.BeACop = 0;
    TheRaceParameters.Boost = 0;
    TheRaceParameters.BoostScale[0] = 0.0f;
    TheRaceParameters.BoostScale[1] = 0.0f;
    memset(&TheDifficultyInfo, 0, sizeof TheDifficultyInfo);
    memset(world.PlayerPositions, 0, sizeof world.PlayerPositions);
    // 11e-4's: no driver honking, both debug switches off.
    memset(ish, 0, sizeof ish);
    SuperEasyAI = 0;
    BoringAIForCameraTuningOn = 0;
    // 11e-5's: the loop counter 0, the default seed as bmath.c starts it,
    // the debug reset off at its angle, an empty car list and car table,
    // and no fake action expired, failed or accomplished.
    WorldLoopCounter = 0;
    bDefaultSeed = 0x12345678u;
    ResetThisCarsPosition = 0;
    ThisCarsResetAngle = 0xc000;
    world.CarList.next = &world.CarList;
    world.CarList.prev = &world.CarList;
    world.TotalNumCars = 0;
    world.AICarPos = 0;
    world.CopCarPos = 0;
    world.TrafficCarPos = 0;
    memset(world.CarTable, 0, sizeof world.CarTable);
    memset(fa_test, 0, sizeof fa_test);
}

// ------------------------------------------------------------ the dumps

static void dump_avg(const char *tag, const Average *a)
{
    int i, n;

    if (a == NULL || is_pat(a)) {
        printf("  %s %s\n", tag, a == NULL ? "null" : "pat");
        return;
    }
    printf("  %s %s slots %d cur %d n %d total %s avg %s data %s\n", tag,
           nm(a), a->nSlots, a->nCurrentSlot, a->nSamples, fx(a->fTotal),
           fx(a->fAverage), nm(a->pData));
    n = a->nSlots;
    if (index_in(a->pData, heap, sizeof heap[0], NHEAP) < 0)
        return;
    if (n > HEAP_BLOCK / 4)
        n = HEAP_BLOCK / 4;
    printf("   ");
    for (i = 0; i < n; i++)
        printf(" %s", fx(a->pData[i]));
    printf("\n");
}

static void dump_loc(const char *tag, const DrivingLocation *l)
{
    printf("  %s %s %s %d %08x\n", tag, nm(l->pRoute), nm(l->pRoutePoint),
           (int)l->DrivingLine,
           (unsigned)l->LastRelaxedDrivingLineSwitchTime.PackedTime);
}

static void dump_ctrl(int k)
{
    AICarController *c = &ctrls[k];
    const DrivingInformation *d = &c->MyCurrentDrivingInformation;
    const NearbyCarList *l = &d->MyNearbyCarList;
    const unsigned char *g = (const unsigned char *)c->sGlueDebug;
    int i;

    printf("  K vt %s car %s drv %s\n", ctl_vt_name(c->Base._vtable),
           nm(c->Base.pCar), nm(c->Base.Driver));
    printf("  K list %s %d %s %s\n   ", nm(l->MyCar), (int)l->NumCarsInArray,
           fx(l->MyHalfSizeL), fx(l->MyHalfSizeD));
    for (i = 0; i < NEARBYCARLIST_MAX; i++)
        printf(" %s", nm(l->Array[i].TheCar));
    printf("\n");
    dump_loc("K iloc", &d->MyDrivingLocation);
    dump_choice(&d->MyDrivingChoice, "K ich");
    printf("  K ptr %s %s %s exc %s ltr %d secs %s force %d act %s\n",
           nm(c->CurrentDrivingLocation), nm(c->CurrentDrivingChoice),
           nm(c->CurrentNearbyCarList),
           nm(c->CarToExcludeFromCollisionPrediction),
           (int)c->LastTrackRouteNumber,
           fx(c->SecondsBeforeNextActionEvaluation),
           (int)c->ForceCurrentAction, nm(c->CurrentAction));
    printf("  K t %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x\n",
           (unsigned)c->LastRoutePointLookaheadSwitch.PackedTime,
           (unsigned)c->LastTimeNonGetUnstuckActionWasCalled.PackedTime,
           (unsigned)c->BrakeStandTimer.PackedTime,
           (unsigned)c->BrakeStandTimerStart.PackedTime,
           (unsigned)c->LastBoostCalculationTime.PackedTime,
           (unsigned)c->OffBeltTimer.PackedTime,
           (unsigned)c->RealPhysicsTimer.PackedTime,
           (unsigned)c->ProgressTimer.PackedTime,
           (unsigned)c->GlueOnTimer.PackedTime,
           (unsigned)c->GlueOffTimer.PackedTime,
           (unsigned)c->TakenSignpostTimer.PackedTime);
    printf("  K la %d pot %s bs %d lp %s glue %s gr %d gb %s boost %d cp %s "
           "sign %d ts %d\n", (int)c->CurrentRoutePointLookahead,
           fx(c->PullOverTimeout), (int)c->BrakeStanding,
           fx(c->fLastProgress), nm(c->pGlueCar), (int)c->nGlueOffReason,
           fx(c->fCurrentGlueTimeBias), (int)c->bBoostAllowed,
           nm(c->pCatchupPlayer), (int)c->nSignpostIndex,
           (int)c->TakenSignpostIndex);
    printf("  K sticky");
    for (i = 0; i < AICC_NUM_STICKY_DECISIONS; i++)
        printf(" %08x", (unsigned)c->aStickyDecisions[i]);
    printf("\n  K gd ");
    for (i = 0; i < 32; i++)
        printf("%02x", g[i]);
    printf("\n  K vp %s %s %s %s\n", fx(c->vPreviousLinePoint.x),
           fx(c->vPreviousLinePoint.y), fx(c->vPreviousLinePoint.z),
           fx(c->vPreviousLinePoint.pad));
    dump_avg("K prog", c->pProgress);
    dump_avg("K dls", c->pDeltaLineSpeed);
}

static void dump_where(int k)
{
    AICarController *c = &ctrls[k];

    dump_loc("K at", c->CurrentDrivingLocation);
    printf("  K ltr %d hl %d %d\n", (int)c->LastTrackRouteNumber,
           (int)HighlightDrivingLineInRouteNumber,
           (int)HighlightDrivingLineNumber);
}

static void dump_signs(int k)
{
    AICarController *c = &ctrls[k];
    int i;

    printf("  S sign %d ts %d tt %08x ltr %d\n", (int)c->nSignpostIndex,
           (int)c->TakenSignpostIndex,
           (unsigned)c->TakenSignpostTimer.PackedTime,
           (int)c->LastTrackRouteNumber);
    printf("  S sticky");
    for (i = 0; i < AICC_NUM_STICKY_DECISIONS; i++)
        printf(" %08x", (unsigned)c->aStickyDecisions[i]);
    printf("\n");
}

static struct Player *plr_ptr(const char *s)
{
    int k = atoi(s);

    return k >= 0 ? &plr[k] : NULL;
}

static void dump_glue(int k)
{
    AICarController *c = &ctrls[k];
    int i;

    printf("  G glue %s on %08x off %08x bias %s reason %d n", nm(c->pGlueCar),
           (unsigned)c->GlueOnTimer.PackedTime,
           (unsigned)c->GlueOffTimer.PackedTime, fx(c->fCurrentGlueTimeBias),
           (int)nLastGlueReason);
    for (i = 0; i < NCARS; i++)
        if (plr_used[i])
            printf(" %d", (int)plr[i].nGlueCount);
    printf("\n");
}

static void dump_honk(int k)
{
    const Car *c = &cars[k];

    printf("  H blink %d honk %d two %d start %08x on %s second %s off %s\n",
           (int)c->WantToBlinkHeadlights, (int)c->WantToHonkHorn,
           (int)c->WantTwoHonksAndOrBlinks,
           (unsigned)c->HeadlightsAndHornStartTime,
           fx(c->HeadlightsAndHornOnDuration),
           fx(c->HeadlightsAndHornSecondOnDuration),
           fx(c->HeadlightsAndHornOffDuration));
}

static void dump_ptd(int i)
{
    const DriveTarget *t = &facts[i].PointsToDrive;

    printf("  E pt%d n %d wpc %d wpt %d len %s lps %d\n", i, (int)t->NumPoints,
           (int)t->WhichPointIPickedCalculationTime,
           (int)t->WhichPointIPickedTime, fx(t->Length),
           (int)t->LastPointToScore);
}

static void dump_facts(void)
{
    int i;

    for (i = 0; i < NFACTS; i++)
        if (facts[i].Base._vtable != 0)
            printf("  fa%d pt %d\n", i,
                   (int)facts[i].PointsToDriveWillExecuteAction);
}

// ------------------------------------------------------------ the ops

static AIAction *fact_ptr(const char *s)
{
    int i = atoi(s);

    return i >= 0 ? &facts[i] : NULL;
}

static DrivingLocation *hl_of(int k, const char *s)
{
    int h = atoi(s);

    if (h < 0)
        return NULL;
    return h == 0 ? &loc : ctrls[k].CurrentDrivingLocation;
}

// 11e-4's ops; 0 for none of them.
static int ac_op4(const char *c, int k, AICarController *a, char **t)
{
    Car *car = &cars[k];

    if (strcmp(c, "ctl") == 0) {
        car->TheControlMode = (ControlMode)atoi(t[2]);
    } else if (strcmp(c, "dt") == 0) {
        drivers[k].TheDriverType = (DriverType)atoi(t[2]);
    } else if (strcmp(c, "hk") == 0) {
        car->WantToBlinkHeadlights = atoi(t[2]);
        car->WantToHonkHorn = atoi(t[3]);
        car->WantTwoHonksAndOrBlinks = atoi(t[4]);
        car->HeadlightsAndHornStartTime = (int32_t)wh(t[5]);
        car->HeadlightsAndHornOnDuration = fh(t[6]);
        car->HeadlightsAndHornSecondOnDuration = fh(t[7]);
        car->HeadlightsAndHornOffDuration = fh(t[8]);
        car->ForceHeadlightsOn = atoi(t[9]);
    } else if (strcmp(c, "ish") == 0) {
        ish[k] = atoi(t[2]);
    } else if (strcmp(c, "mh") == 0) {
        NearbyCarList *l = atoi(t[3]) == 0
                           ? &list
                           : &a->MyCurrentDrivingInformation.MyNearbyCarList;

        aicarcontroller_maybe_honk_and_or_blink_headlights(a, car_ptr(t[2]),
                                                           l);
        dump_honk(k);
    } else if (strcmp(c, "hr") == 0) {
        car_honk_and_or_blink_headlights(car, fh(t[2]), fh(t[3]), fh(t[4]),
                                         atoi(t[5]), atoi(t[6]), atoi(t[7]));
        dump_honk(k);
    } else if (strcmp(c, "uh") == 0) {
        car_update_headlights_and_horn(car);
        printf("  L state %d\n", (int)car->HeadlightsState);
    } else if (strcmp(c, "ad") == 0) {
        AIAction *f = &facts[k];

        f->UseDrivingLineSpeed = atoi(t[2]);
        f->DesiredSpeed = fh(t[3]);
        f->TimeToGetToDesiredSpeed = fh(t[4]);
        f->DesiredSpeedTolerance = fh(t[5]);
        f->AllowedToUseThrottleAndBrake = atoi(t[6]);
    } else if (strcmp(c, "at") == 0) {
        DriveTarget *p = &facts[k].PointsToDrive;

        p->NumPoints = (int8_t)atoi(t[2]);
        p->Length = fh(t[3]);
        p->WhichPointIPickedCalculationTime = 5;
        p->WhichPointIPickedTime = 7;
        p->LastPointToScore = 3;
    } else if (strcmp(c, "sea") == 0) {
        SuperEasyAI = k;
    } else if (strcmp(c, "bai") == 0) {
        BoringAIForCameraTuningOn = k;
    } else if (strcmp(c, "lsp") == 0) {
        routes[k].TrackRoutePointTable[atoi(t[2])]
            .DrivingLineSpeeds[atoi(t[3])] = (uint8_t)atoi(t[4]);
    } else if (strcmp(c, "eca") == 0) {
        aicarcontroller_execute_current_action(a);
        printf("  E la %d lrs %08x boost %s\n",
               (int)a->CurrentRoutePointLookahead,
               (unsigned)a->LastRoutePointLookaheadSwitch.PackedTime,
               fx(car->State.BoostFactor));
        dump_ptd(atoi(t[2]));
    } else {
        return 0;
    }
    return 1;
}

// After a think: the controller, the seed, the debug reset's switch, the
// car's movement mode, the world's two counts, the action and the fakes.
static void dump_think(int k)
{
    const AIAction *a = ctrls[k].CurrentAction;

    dump_ctrl(k);
    printf("  T seed %08x rtp %d mode %d ids %d %d\n", (unsigned)bDefaultSeed,
           (int)ResetThisCarsPosition, (int)cars[k].TheMovementMode,
           (int)world.CollisionPredictionID,
           (int)world.PotentialDriveTargetID);
    if (a != NULL)
        printf("  T act type %d st %d pt %d\n", (int)a->Type,
               (int)a->Base.Status, (int)a->PointsToDriveWillExecuteAction);
    dump_facts();
}

// 11e-5's ops; 0 for none of them.
static int ac_op5(const char *c, int k, AICarController *a, char **t, int n)
{
    if (strcmp(c, "rs") == 0) {
        race.RaceStage = k;
    } else if (strcmp(c, "wlc") == 0) {
        WorldLoopCounter = k;
    } else if (strcmp(c, "wt") == 0) {
        int i;

        world.TotalNumCars = k;
        world.AICarPos = atoi(t[2]);
        world.CopCarPos = atoi(t[3]);
        world.TrafficCarPos = atoi(t[4]);
        memset(world.CarTable, 0, sizeof world.CarTable);
        for (i = 0; i < WORLD_MAX_CARS && 5 + i < n; i++)
            world.CarTable[i] = car_ptr(t[5 + i]);
    } else if (strcmp(c, "cl") == 0) {
        // The world's car list, in the script's order, each car in it
        // rendering and not poofed.
        CarNode *head = (CarNode *)(void *)&world.CarList, *prev = head;
        int i;

        for (i = 1; i < n; i++) {
            Car *car = car_ptr(t[i]);

            prev->next = &car->Link;
            car->Link.prev = prev;
            car->RenderingEnabled = 1;
            car->bPoofed = 0;
            prev = &car->Link;
        }
        prev->next = head;
        head->prev = prev;
    } else if (strcmp(c, "seed") == 0) {
        bDefaultSeed = wh(t[1]);
    } else if (strcmp(c, "rtp") == 0) {
        ResetThisCarsPosition = k;
        ThisCarsResetAngle = (uint16_t)atoi(t[2]);
    } else if (strcmp(c, "dl") == 0) {
        rcars[k].dCurrentLapNumberExact = fh(t[2]);
    } else if (strcmp(c, "pg") == 0) {
        Average *v = a->pProgress;

        v->nCurrentSlot = (uint8_t)atoi(t[2]);
        v->nSamples = (uint8_t)atoi(t[3]);
        v->fTotal = fh(t[4]);
        v->pData[v->nCurrentSlot] = fh(t[5]);
    } else if (strcmp(c, "fs") == 0) {
        facts[k].Base.CanExpire = atoi(t[2]);
        fa_test[k][0] = atoi(t[3]);
        fa_test[k][1] = atoi(t[4]);
        fa_test[k][2] = atoi(t[5]);
    } else if (strcmp(c, "think") == 0) {
        aicarcontroller_think(a, fh(t[2]));
        dump_think(k);
    } else if (strcmp(c, "tcd") == 0) {
        Timer tm;
        int got;

        tm.PackedTime = wh(t[1]);
        got = timer_count_down(&tm, fh(t[2]));
        printf("  tcd %d %08x\n", got, (unsigned)tm.PackedTime);
    } else if (strcmp(c, "cas") == 0) {
        printf("  cas %d\n", race_can_ai_cars_start_driving(pCurrentRace));
    } else {
        return 0;
    }
    return 1;
}

static void ac_op(char **t, int n)
{
    const char *c = t[0];
    int k;
    AICarController *a;

    if (c[0] != '%') {
        op(t, n);
        return;
    }
    c++;
    k = n > 1 ? atoi(t[1]) : 0;
    a = &ctrls[k < 0 || k >= NCARS ? 0 : k];
    if (strcmp(c, "d") == 0) {
        cars[k].TheTrackPathCoordinate.DistanceAroundTrack = fh(t[2]);
    } else if (strcmp(c, "S") == 0) {
        signs[k].Distance = fh(t[2]);
    } else if (strcmp(c, "NS") == 0) {
        NumSignposts = (uint32_t)k;
    } else if (strcmp(c, "U") == 0) {
        TrackRoute *r = &routes[k];

        r->fStartDistance = fh(t[2]);
        r->fEndDistance = fh(t[3]);
        r->BBoxMin.x = fh(t[4]);
        r->BBoxMin.y = fh(t[5]);
        r->BBoxMax.x = fh(t[6]);
        r->BBoxMax.y = fh(t[7]);
    } else if (strcmp(c, "a") == 0) {
        cars[k].State.Angle = (uint16_t)atoi(t[2]);
    } else if (strcmp(c, "mm") == 0) {
        cars[k].TheMovementMode = (MovementMode)atoi(t[2]);
    } else if (strcmp(c, "pl") == 0) {
        cars[k].pPlayer = atoi(t[2]) ? (Player *)(void *)players[k] : NULL;
    } else if (strcmp(c, "bf") == 0) {
        cars[k].State.BoostFactor = fh(t[2]);
    } else if (strcmp(c, "ci") == 0) {
        cars[k].CarIndex = (int16_t)atoi(t[2]);
    } else if (strcmp(c, "pos") == 0) {
        cars[k].State.Position.x = fh(t[2]);
        cars[k].State.Position.y = fh(t[3]);
        cars[k].State.Position.z = fh(t[4]);
    } else if (strcmp(c, "vp") == 0) {
        a->vPreviousLinePoint.x = fh(t[2]);
        a->vPreviousLinePoint.y = fh(t[3]);
        a->vPreviousLinePoint.z = fh(t[4]);
        a->vPreviousLinePoint.pad = fh(t[5]);
    } else if (strcmp(c, "cp") == 0) {
        // Route k's points over route t[2]'s, but for each point's own
        // route number, its last byte.
        TrackRoute *from = &routes[k], *to = &routes[atoi(t[2])];
        int32_t i, np = from->NumPoints < to->NumPoints ? from->NumPoints
                                                       : to->NumPoints;

        for (i = 0; i < np; i++)
            memcpy(&to->TrackRoutePointTable[i],
                   &from->TrackRoutePointTable[i],
                   offsetof(TrackRoutePoint, RouteNumber));
    } else if (strcmp(c, "G") == 0) {
        nDefaultMovementMode = k;
    } else if (strcmp(c, "n") == 0) {
        fill(a, sizeof *a);
        aicarcontroller_init(a, &cars[k]);
        dump_ctrl(k);
    } else if (strcmp(c, "x") == 0) {
        aicarcontroller_destroy(a, atoi(t[2]));
        printf("  vt %s\n", ctl_vt_name(a->Base._vtable));
    } else if (strcmp(c, "K") == 0) {
        dump_ctrl(k);
    } else if (strcmp(c, "v") == 0) {
        static const uint32_t vts[] = { AICARCONTROLLER_VTABLE, TVT, CVT };

        a->Base._vtable = vts[atoi(t[2])];
    } else if (strcmp(c, "dr") == 0) {
        a->Base.Driver = &cdrivers[k];
    } else if (strcmp(c, "J") == 0) {
        a->MyCurrentDrivingInformation.MyNearbyCarList = list;
        a->MyCurrentDrivingInformation.MyDrivingLocation = loc;
        a->MyCurrentDrivingInformation.MyDrivingChoice = choice;
    } else if (strcmp(c, "L") == 0) {
        DrivingLocation *l = a->CurrentDrivingLocation;

        l->pRoute = route_of(t[2]);
        l->pRoutePoint = point_of(t[2], t[3]);
        l->DrivingLine = atoi(t[4]);
        l->LastRelaxedDrivingLineSwitchTime.PackedTime = wh(t[5]);
    } else if (strcmp(c, "ch") == 0) {
        set_choice(a->CurrentDrivingChoice, t + 1);
    } else if (strcmp(c, "sk") == 0) {
        int i;

        for (i = 0; i < AICC_NUM_STICKY_DECISIONS; i++)
            a->aStickyDecisions[i] = wh(t[2 + i]);
    } else if (strcmp(c, "rn") == 0) {
        rnum_first[k] = atoi(t[2]);
        rnum_last[k] = atoi(t[3]);
    } else if (strcmp(c, "q") == 0) {
        int i;

        nchoose = ichoose = 0;
        for (i = 1; i < n && nchoose < 16; i++)
            choose_q[nchoose++] = atoi(t[i]);
    } else if (strcmp(c, "fa") == 0) {
        AIAction *f = &facts[k];

        memset(f, 0, sizeof *f);
        f->Base._vtable = AVT;
        f->Type = atoi(t[2]);
        f->Score = atoi(t[3]);
        fa_pt[k] = atoi(t[4]);
        f->PointsToDriveWillExecuteAction = atoi(t[5]);
    } else if (strcmp(c, "cur") == 0) {
        a->CurrentAction = fact_ptr(t[2]);
    } else if (strcmp(c, "sr") == 0) {
        aicarcontroller_set_current_route(a, route_of(t[2]),
                                          point_of(t[2], t[3]));
        dump_where(k);
    } else if (strcmp(c, "gr") == 0) {
        printf("  route %s\n",
               nm(aicarcontroller_get_current_route(a, atoi(t[2]))));
        dump_where(k);
    } else if (strcmp(c, "gp") == 0) {
        printf("  point %s\n",
               nm(aicarcontroller_get_current_route_point(a, atoi(t[2]))));
        dump_where(k);
    } else if (strcmp(c, "oob") == 0) {
        printf("  oob %s\n", fx(aicarcontroller_get_amount_out_of_bounds(a)));
    } else if (strcmp(c, "fw") == 0) {
        aicarcontroller_find_where_i_am(a);
        dump_where(k);
    } else if (strcmp(c, "fc") == 0) {
        aicarcontroller_find_closest_track_route(a, atoi(t[2]), atoi(t[3]));
        dump_where(k);
    } else if (strcmp(c, "gl") == 0) {
        int32_t line;
        int got;

        fill(&line, sizeof line);
        got = aicarcontroller_get_new_driving_line(
            a, route_of(t[2]), point_of(t[2], t[3]), atoi(t[4]), &line,
            hl_of(k, t[5]));
        printf("  line %d %d\n", got, (int)line);
        dump_where(k);
        dump_after();
    } else if (strcmp(c, "jr") == 0) {
        aicarcontroller_just_reset(a);
        dump_ctrl(k);
    } else if (strcmp(c, "dn") == 0) {
        printf("  dnum %d\n", (int)aicarcontroller_get_my_driver_number(a));
    } else if (strcmp(c, "cs") == 0) {
        int i;

        aicarcontroller_clear_sticky_decisions(a);
        printf("  sticky");
        for (i = 0; i < AICC_NUM_STICKY_DECISIONS; i++)
            printf(" %08x", (unsigned)a->aStickyDecisions[i]);
        printf("\n");
    } else if (strcmp(c, "st") == 0) {
        aicarcontroller_steer_straight_ahead(a);
    } else if (strcmp(c, "cn") == 0) {
        AIAction *got = fact_ptr("-1");

        aicarcontroller_choose_new_action(a, &got, atoi(t[2]));
        printf("  chosen %s\n", nm(got));
    } else if (strcmp(c, "ia") == 0) {
        AIAction *got = aicarcontroller_interrupt_action(a);

        printf("  interrupt %s force %d act %s\n", nm(got),
               (int)a->ForceCurrentAction, nm(a->CurrentAction));
    } else if (strcmp(c, "gpf") == 0) {
        aicarcontroller_generate_points_to_fulfill_action(a, fact_ptr(t[2]));
        printf("  act %s\n", nm(a->CurrentAction));
        dump_facts();
        dump_where(k);
    } else if (strcmp(c, "cat") == 0) {
        printf("  atype %d\n", (int)aicarcontroller_get_current_action_type(a));
    } else if (strcmp(c, "force") == 0) {
        aicarcontroller_force_my_current_action(a, atoi(t[2]));
        printf("  force %d\n", (int)a->ForceCurrentAction);
    } else if (strcmp(c, "pm") == 0) {
        aicarcontroller_set_to_physics_mode(a, car_ptr(t[2]));
        printf("  movement %d ob %08x rp %08x\n", (int)cars[k].TheMovementMode,
               (unsigned)a->OffBeltTimer.PackedTime,
               (unsigned)a->RealPhysicsTimer.PackedTime);
    } else if (strcmp(c, "cc") == 0) {
        carcontroller_set_to_physics_mode(&a->Base, car_ptr(t[2]));
        printf("  movement %d\n", (int)cars[k].TheMovementMode);
    } else if (strcmp(c, "ls") == 0) {
        printf("  lspeed %s\n",
               fx(aicarcontroller_get_current_driving_line_speed(a)));
    } else if (strcmp(c, "seam") == 0) {
        printf("  lspeed %s\n", fx(aicarcontroller_line_speed_seam(&a->Base)));
    } else if (strcmp(c, "fb") == 0) {
        aicarcontroller_force_boost(a, fh(t[2]));
        printf("  boost %s %d\n", fx(cars[k].State.BoostFactor),
               (int)a->bBoostAllowed);
    } else if (strcmp(c, "rb") == 0) {
        aicarcontroller_release_boost(a);
        printf("  boost %s %d\n", fx(cars[k].State.BoostFactor),
               (int)a->bBoostAllowed);
    } else if (strcmp(c, "af") == 0) {
        printf("  fly %d\n", (int)aicarcontroller_about_to_fly(a, fh(t[2])));
    } else if (strcmp(c, "ob") == 0) {
        aicarcontroller_set_off_belt_timer(a, fh(t[2]));
        printf("  ob %08x\n", (unsigned)a->OffBeltTimer.PackedTime);
    } else if (strcmp(c, "ex") == 0) {
        aicarcontroller_set_car_to_exclude_from_collision_prediction(
            a, car_ptr(t[2]));
        printf("  exc %s\n", nm(a->CarToExcludeFromCollisionPrediction));
    } else if (strcmp(c, "gx") == 0) {
        printf("  exc %s\n",
               nm(aicarcontroller_get_car_to_exclude_from_collision_prediction(
                   a)));
    } else if (strcmp(c, "gdl") == 0) {
        printf("  dloc %s\n",
               nm(aicarcontroller_get_current_driving_location(a)));
    } else if (strcmp(c, "dd") == 0) {
        aicarcontroller_debug_display(a);
    // 11e-2's.
    } else if (strcmp(c, "rnd") == 0) {
        int i;

        nrq = irq = 0;
        for (i = 0; i < k && i < NRANDOM && 2 + i < n; i++) {
            rqw[nrq] = wh(t[2 + i]);
            rq[nrq++] = fh(t[2 + i]);
        }
    } else if (strcmp(c, "tg") == 0) {
        tinfo.SignpostGracePeriod = k;
    } else if (strcmp(c, "tn") == 0) {
        TheRaceParameters.TrackNumber = k;
    } else if (strcmp(c, "rt") == 0) {
        race.RaceTime.PackedTime = wh(t[2]);
    } else if (strcmp(c, "si") == 0) {
        a->nSignpostIndex = atoi(t[2]);
    } else if (strcmp(c, "ts") == 0) {
        a->TakenSignpostIndex = atoi(t[2]);
    } else if (strcmp(c, "hl") == 0) {
        a->MyCurrentDrivingInformation.MyNearbyCarList.MyHalfSizeL = fh(t[2]);
    } else if (strcmp(c, "vm") == 0) {
        cars[k].State.VelocityMagnitude = fh(t[2]);
    } else if (strcmp(c, "tsc") == 0) {
        int i;

        for (i = 0; i < 3; i++)
            TheDifficultyInfo.AISkillLevel[k].TakeSignChance[i] = fh(t[2 + i]);
    } else if (strcmp(c, "sf") == 0) {
        signs[k].Flags = (uint8_t)atoi(t[2]);
        signs[k].AIHint = atoi(t[3]);
    } else if (strcmp(c, "fsi") == 0) {
        aicarcontroller_find_signpost_index(a);
        printf("  sign %d\n", (int)a->nSignpostIndex);
    } else if (strcmp(c, "gsi") == 0) {
        printf("  free %d\n", (int)aicarcontroller_get_sticky_index(a));
    } else if (strcmp(c, "dsd") == 0) {
        aicarcontroller_do_sticky_decisions(a);
        dump_signs(k);
        dump_where(k);
    } else if (strcmp(c, "spd") == 0) {
        int32_t line = atoi(t[3]);
        int got = aicarcontroller_sign_post_decision(
            a, &signs[atoi(t[2])], &line, a->CurrentDrivingLocation);

        printf("  take %d line %d\n", got, (int)line);
        dump_signs(k);
        dump_where(k);
    } else if (strcmp(c, "gct") == 0) {
        aicarcontroller_get_current_track_route_point(a, &cars[k]);
        dump_signs(k);
        dump_where(k);
    // 11e-3's.
    } else if (strcmp(c, "P") == 0) {
        struct Player *p = &plr[k];
        Average *v = &pavg[k];

        memset(p, 0, sizeof *p);
        memset(v, 0, sizeof *v);
        p->MyCar = &cars[k];
        p->PlayerNumber = atoi(t[2]);
        p->pAverageSpeedRatio = v;
        v->fAverage = fh(t[3]);
        p->fMaxSpeedRatio = fh(t[4]);
        v->nSlots = (uint8_t)atoi(t[5]);
        v->nSamples = (uint8_t)atoi(t[6]);
        p->nGlueCount = atoi(t[7]);
        cars[k].pPlayer = p;
        plr_used[k] = 1;
    } else if (strcmp(c, "PT") == 0) {
        int i;

        PlayerNumPlayers = k;
        for (i = 0; i < 2; i++) {
            PlayerPlayersByIndex[i] = plr_ptr(t[2 + i]);
            PlayerPlayersByNumber[i] = plr_ptr(t[4 + i]);
        }
    } else if (strcmp(c, "rc") == 0) {
        if (strcmp(t[2], "x") == 0) {
            cars[k].pRacingCar = NULL;
        } else {
            memset(&rcars[k], 0, sizeof rcars[k]);
            rcars[k].pCar = &cars[k];
            rcars[k].RacePosition = (int8_t)atoi(t[2]);
            rcars[k].CurrentLapNumberExact = fh(t[3]);
            cars[k].pRacingCar = &rcars[k];
        }
    } else if (strcmp(c, "RC") == 0) {
        rcoord[0] = (uint32_t)k;
    } else if (strcmp(c, "rp") == 0) {
        TheRaceParameters.NumPlayerCars = atoi(t[1]);
        TheRaceParameters.NumAICars = atoi(t[2]);
        TheRaceParameters.BeACop = atoi(t[3]);
        TheRaceParameters.Boost = atoi(t[4]);
        TheRaceParameters.BoostScale[0] = fh(t[5]);
        TheRaceParameters.BoostScale[1] = fh(t[6]);
    } else if (strcmp(c, "sfe") == 0) {
        skipfe = k;
        SkipFEBeACop = atoi(t[2]);
    } else if (strcmp(c, "dw") == 0) {
        int i;

        for (i = 2; i < n; i++) {
            uint32_t v = wh(t[i]);

            memcpy((char *)&TheDifficultyInfo + k + 4 * (i - 2), &v, 4);
        }
    } else if (strcmp(c, "gds") == 0) {
        gds[k] = fh(t[2]);
    } else if (strcmp(c, "wp") == 0) {
        world.PlayerPositions[k].x = fh(t[2]);
        world.PlayerPositions[k].y = fh(t[3]);
        world.PlayerPositions[k].z = fh(t[4]);
    } else if (strcmp(c, "bm") == 0) {
        bBeltMover = k;
    } else if (strcmp(c, "dc") == 0) {
        CarControllerDisableCatchup = k;
    } else if (strcmp(c, "ab") == 0) {
        facts[k].AllowedToUseBoost = atoi(t[2]);
    } else if (strcmp(c, "np") == 0) {
        cdrivers[k].MyDriveTarget.NumPoints = (int8_t)atoi(t[2]);
    } else if (strcmp(c, "vel") == 0) {
        cars[k].State.Velocity.x = fh(t[2]);
        cars[k].State.Velocity.y = fh(t[3]);
        cars[k].State.Velocity.z = fh(t[4]);
    } else if (strcmp(c, "fsw") == 0) {
        cars[k].State.ForwardSpeed = fh(t[2]);
        cars[k].State.nWheelsTouchingGround = atoi(t[3]);
    } else if (strcmp(c, "kf") == 0) {
        const char *f = t[2];

        if (strcmp(f, "lbt") == 0)
            a->LastBoostCalculationTime.PackedTime = wh(t[3]);
        else if (strcmp(f, "ob") == 0)
            a->OffBeltTimer.PackedTime = wh(t[3]);
        else if (strcmp(f, "rp") == 0)
            a->RealPhysicsTimer.PackedTime = wh(t[3]);
        else if (strcmp(f, "on") == 0)
            a->GlueOnTimer.PackedTime = wh(t[3]);
        else if (strcmp(f, "off") == 0)
            a->GlueOffTimer.PackedTime = wh(t[3]);
        else if (strcmp(f, "glue") == 0)
            a->pGlueCar = car_ptr(t[3]);
        else if (strcmp(f, "bias") == 0)
            a->fCurrentGlueTimeBias = fh(t[3]);
        else if (strcmp(f, "ba") == 0)
            a->bBoostAllowed = atoi(t[3]);
        else if (strcmp(f, "cp") == 0)
            a->pCatchupPlayer = plr_ptr(t[3]);
        else if (strcmp(f, "lrs") == 0)
            a->LastRoutePointLookaheadSwitch.PackedTime = wh(t[3]);
        else if (strcmp(f, "la") == 0)
            a->CurrentRoutePointLookahead = atoi(t[3]);
        else if (strcmp(f, "tt") == 0)
            a->TakenSignpostTimer.PackedTime = wh(t[3]);
        else if (strcmp(f, "bs") == 0)
            a->BrakeStandTimer.PackedTime = wh(t[3]);
        else if (strcmp(f, "bss") == 0)
            a->BrakeStandTimerStart.PackedTime = wh(t[3]);
        else if (strcmp(f, "bsg") == 0)
            a->BrakeStanding = atoi(t[3]);
        else if (strcmp(f, "pt") == 0)
            a->ProgressTimer.PackedTime = wh(t[3]);
        else if (strcmp(f, "secs") == 0)
            a->SecondsBeforeNextActionEvaluation = fh(t[3]);
        else {
            fprintf(stderr, "bad field %s\n", f);
            exit(2);
        }
    } else if (strcmp(c, "whb") == 0) {
        printf("  belt %d\n", aicarcontroller_we_have_the_belt(a));
    } else if (strcmp(c, "wnb") == 0) {
        printf("  belt %d\n", aicarcontroller_we_need_the_belt(a));
    } else if (strcmp(c, "wcb") == 0) {
        printf("  belt %d\n", aicarcontroller_we_can_have_the_belt(a));
    } else if (strcmp(c, "whg") == 0) {
        printf("  glue %d\n", aicarcontroller_we_have_the_glue(a));
    } else if (strcmp(c, "wng") == 0) {
        printf("  glue %d\n", aicarcontroller_we_need_the_glue(a));
    } else if (strcmp(c, "wcg") == 0) {
        printf("  glue %d\n",
               aicarcontroller_we_can_have_the_glue(a, plr_ptr(t[2])));
        dump_glue(k);
    } else if (strcmp(c, "gon") == 0) {
        aicarcontroller_glue_on(a, plr_ptr(t[2]));
        dump_glue(k);
    } else if (strcmp(c, "goff") == 0) {
        aicarcontroller_glue_off(a);
        dump_glue(k);
    } else if (strcmp(c, "ggs") == 0) {
        printf("  gspeed %s\n", fx(aicarcontroller_get_glue_speed(a)));
    } else if (strcmp(c, "cdp") == 0) {
        float d, p;

        fill(&d, sizeof d);
        fill(&p, sizeof p);
        aicarcontroller_calculate_distance_and_position_boost(
            a, &rcars[atoi(t[2])], &rcars[atoi(t[3])], &d, &p);
        printf("  dpb %s %s\n", fx(d), fx(p));
    } else if (strcmp(c, "dbf") == 0) {
        aicarcontroller_decide_boost_factor(a);
        printf("  boost %s lbt %08x cp %s\n", fx(cars[k].State.BoostFactor),
               (unsigned)a->LastBoostCalculationTime.PackedTime,
               nm(a->pCatchupPlayer));
    } else if (!ac_op4(c, k, a, t) && !ac_op5(c, k, a, t, n)) {
        fprintf(stderr, "bad op %s\n", t[0]);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    if (argc != 2) {
        fprintf(stderr, "usage: aicarcontroller_test SCRIPT\n");
        return 2;
    }
    dc_setup();
    aicarcontroller_install_vtables();
    carcontroller_install_vtables();
    {
        // The port's own table, copied as the model copies retail's, with
        // the script's GetRouteNumbersToUse and ChooseNewAction.
        int n;
        const VtEntry *k = vt_table(AICARCONTROLLER_VTABLE, &n);

        if (k == NULL || n != AICARCONTROLLER_VT_ENTRIES) {
            fprintf(stderr, "no AICarController table\n");
            return 2;
        }
        memcpy(tvt, k, sizeof tvt);
        tvt[VT_SLOT(AICARCONTROLLER_VT_GET_ROUTE_NUMBERS_TO_USE)].fn =
            (VtFn)fk_route_numbers;
        tvt[VT_SLOT(AICARCONTROLLER_VT_CHOOSE_NEW_ACTION)].fn =
            (VtFn)fk_choose;
        vt_install(TVT, tvt, AICARCONTROLLER_VT_ENTRIES);
    }
    memset(avt, 0, sizeof avt);
    avt[VT_SLOT(AIACTION_VT_DTOR)].fn = (VtFn)fk_action_dtor;
    avt[VT_SLOT(AIACTION_VT_CALCULATE_POINTS_TO_DRIVE)].fn =
        (VtFn)fk_action_points;
    avt[VT_SLOT(AIACTION_VT_HAS_EXPIRED)].fn = (VtFn)fk_has_expired;
    avt[VT_SLOT(AIACTION_VT_HAS_FAILED)].fn = (VtFn)fk_has_failed;
    avt[VT_SLOT(AIACTION_VT_HAS_BEEN_ACCOMPLISHED)].fn =
        (VtFn)fk_has_been_accomplished;
    vt_install(AVT, avt, AIACTION_VT_ENTRIES);
    drv_vt[VT_SLOT(CARDRIVER_VT_SET_STEER_TO_POINT)].fn =
        (VtFn)fk_set_steer_to_point;
    drv_vt[VT_SLOT(CARDRIVER_VT_ZERO_STEERING_MEMORY)].fn =
        (VtFn)fk_zero_steering_memory;
    drv_vt[VT_SLOT(CARDRIVER_VT_GET_DESIRED_SPEED)].fn =
        (VtFn)fk_get_desired_speed;
    drv_vt[VT_SLOT(CARDRIVER_VT_SET_DESIRED_SPEED)].fn =
        (VtFn)fk_set_desired_speed;
    drv_vt[VT_SLOT(CARDRIVER_VT_SET_TARGET)].fn = (VtFn)fk_set_target;
    drv_vt[VT_SLOT(CARDRIVER_VT_START_HONK_HORN)].fn = (VtFn)fk_start_honk;
    drv_vt[VT_SLOT(CARDRIVER_VT_STOP_HONK_HORN)].fn = (VtFn)fk_stop_honk;
    drv_vt[VT_SLOT(CARDRIVER_VT_IS_HONKING)].fn = (VtFn)fk_is_honking;
    vt_install(DVT, drv_vt, CARDRIVER_VT_ENTRIES);
    nm_more = ac_nm;
    reset_more = ac_reset;
    bSetMemoryHooks(malloc_hook, free_hook);
    return dc_run(argv[1], ac_op);
}
