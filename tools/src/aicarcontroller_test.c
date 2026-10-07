// Host harness for 3DS Files/source/aicarcontroller.c, the AI car
// controller (step 11e-1). Runs the op script tools/aicarcontroller_check.py
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
// and CalculatePointsToDrive print, each printing a line as the checker's
// stubs do.
//
// A float prints as its bits, every NaN as "nan", and a pointer by what it
// points at. The ops and every line's format are the checker's.
#include "drivingchoice_world.inc"

#include "average.h"
#include "bmem.h"
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
    } else {
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
    vt_install(AVT, avt, AIACTION_VT_ENTRIES);
    drv_vt[VT_SLOT(CARDRIVER_VT_SET_STEER_TO_POINT)].fn =
        (VtFn)fk_set_steer_to_point;
    drv_vt[VT_SLOT(CARDRIVER_VT_ZERO_STEERING_MEMORY)].fn =
        (VtFn)fk_zero_steering_memory;
    vt_install(DVT, drv_vt, CARDRIVER_VT_ENTRIES);
    nm_more = ac_nm;
    reset_more = ac_reset;
    bSetMemoryHooks(malloc_hook, free_hook);
    return dc_run(argv[1], ac_op);
}
