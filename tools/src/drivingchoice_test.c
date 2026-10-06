// Host harness for 3DS Files/source/drivingchoice.c, the choices an AI car
// makes about where to drive and the walk along the route that fills its
// drive target, and for Race::GracePeriodIsActive in racecore.c. Runs the
// op script tools/drivingchoice_check.py writes and prints the transcript
// it diffs against the retail image, run in mipsemu over the same script.
//
// The harness owns the cars, their controllers, choices and actions, the
// list, the location, the routes and the signs, and three answers: the
// sign decision (through gAISignPostDecisionFn) and each car's route point
// and amount out of bounds (through the controller's vtable), each of
// which prints a line as the checker's stubs do. Everything else is the
// port's own: nearbycar.c, drivinglocation.c, drivetarget.c, trackroute.c
// and the maths.
//
// A float prints as its bits, every NaN as "nan", and a pointer by what it
// points at. The ops and every line's format are the checker's.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "aicarcontroller.h"
#include "car.h"
#include "carcollisionpredict.h"
#include "collisionbody.h"
#include "carcontroller.h"
#include "cardriver.h"
#include "cartypeinfo.h"
#include "drivetarget.h"
#include "drivingchoice.h"
#include "drivinglocation.h"
#include "nearbycar.h"
#include "race.h"
#include "racecore.h"
#include "track.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"
#include "worldobject.h"

#define NCARS   16
#define NROUTES 6
#define NSIGNS  32
#define LINES   21
#define PAT     0xa5

// The world clock's, here rather than linked from realtime.c, which would
// bring the joylog in behind it (as tools/src/realdriver_test.c).
int32_t WorldTimer;
int32_t WorldTimeFrames;
float   WorldTimeElapsed;

// carcollisionbody.c's, which would bring the collision code with it.
int32_t WilliamsAITuningMode;

// racecore.c's boundary code reaches this; nothing here calls it.
// gWorldObjectDeleteFn, which its destructor reaches too, is obb.c's.

TrackPositionMarker *track_get_position_marker_named(const char *name, int i)
{
    (void)name;
    (void)i;
    fprintf(stderr, "track_get_position_marker_named called\n");
    exit(2);
}

static Car cars[NCARS];
static AICarController ctrls[NCARS];
static DrivingLocation locs[NCARS];
static DrivingChoice choices[NCARS];
static AIAction actions[NCARS];
static CarTypeInfo ctis[NCARS];
static DriverInfo drivers[NCARS];
static CarDriver cdrivers[NCARS];
static uint32_t players[NCARS][4];   // a player, never read
static TrackRoutePoint *rps[NCARS];
static float oobs[NCARS];
static TrackRoute routes[NROUTES];
static Signpost signs[NSIGNS];
static int dec_take[NSIGNS];
static int32_t dec_line[NSIGNS];
static NearbyCarList list;
static DrivingLocation loc;
static DrivingChoice choice, other;
static FuturePointList fpl;
static float lval;
static DriveTarget target;
static Race race;
static CarCollisionBody bodies[NCARS];
static World world;
static OBB obbs[DRIVETARGET_MAX_POINTS], obb_a, obb_b;
static float outs[2];
// TryChoice's best and its way round.
static DrivingChoice best_ch, round_ch;
static DriveTarget target2, target3;

static struct {
    TrackRoute      *route;
    TrackRoutePoint *point;
    int32_t          pn;
    float            off;
    int              crossed;
    int32_t          line;
} walk;

static TrackRoute *cur_route;
static int cur_n;

static VtEntry ctl_vt[CARCONTROLLER_VT_ENTRIES];

static void fill(void *p, size_t n)
{
    memset(p, PAT, n);
}

static int is_pat(const void *p)
{
    uintptr_t v = (uintptr_t)p;
    size_t i;

    for (i = 0; i < sizeof v; i++)
        if (((v >> (8 * i)) & 0xff) != PAT)
            return 0;
    return 1;
}

// Whether a float no longer holds the fill.
static int written(const float *f)
{
    uint32_t u;

    memcpy(&u, f, 4);
    return u != 0xa5a5a5a5u;
}

static int index_in(const void *p, const void *base, size_t stride, int n)
{
    ptrdiff_t off = (const char *)p - (const char *)base;

    if (off < 0 || off >= (ptrdiff_t)(stride * (size_t)n)
        || off % (ptrdiff_t)stride != 0)
        return -1;
    return (int)(off / (ptrdiff_t)stride);
}

static const char *nm(const void *p)
{
    static char buf[16][32];
    static int slot;
    char *b = buf[slot++ & 15];
    int i;

    if (p == NULL)
        return "null";
    if (is_pat(p))
        return "pat";
#define TRY(arr, n, tag)                                                \
    if ((i = index_in(p, arr, sizeof arr[0], n)) >= 0) {                \
        sprintf(b, tag "%d", i);                                         \
        return b;                                                       \
    }
    TRY(cars, NCARS, "c")
    TRY(ctrls, NCARS, "k")
    TRY(locs, NCARS, "L")
    TRY(choices, NCARS, "ch")
    TRY(actions, NCARS, "a")
    TRY(signs, NSIGNS, "S")
    TRY(list.Array, NEARBYCARLIST_MAX, "e")
#undef TRY
    if (p == &loc)
        return "loc";
    if (p == &choice)
        return "CH";
    if (p == &other)
        return "OT";
    for (i = 0; i < NROUTES; i++) {
        const TrackRoute *r = &routes[i];
        int j;

        if (p == r) {
            sprintf(b, "R%d", i);
            return b;
        }
        j = index_in(p, r->TrackRoutePointTable, sizeof(TrackRoutePoint),
                     TRACK_ROUTE_MAX_POINTS);
        if (j >= 0) {
            sprintf(b, "R%d:%d", i, j);
            return b;
        }
    }
    sprintf(b, "?%08lx", (unsigned long)(uint32_t)(uintptr_t)p);
    return b;
}

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static const char *fx(float f)
{
    static char buf[16][12];
    static int slot;
    char *b = buf[slot++ & 15];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08x", (unsigned)u);
    return b;
}

static float fh(const char *s)
{
    uint32_t u = (uint32_t)strtoul(s, NULL, 16);
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static uint32_t wh(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 16);
}

// ------------------------------------------------------------ the stubs

static int sign_decision(AICarController *c, Signpost *s, int32_t *line,
                         DrivingLocation *l)
{
    int i = (int)(s - signs);

    printf("  sign %s %s %d %s\n", nm(c), nm(s), (int)*line, nm(l));
    if (dec_line[i] >= 0)
        *line = dec_line[i];
    return dec_take[i];
}

static int ctrl_index(void *self)
{
    int i = index_in(self, ctrls, sizeof ctrls[0], NCARS);

    if (i < 0) {
        fprintf(stderr, "a controller that is not one of ours\n");
        exit(2);
    }
    return i;
}

static TrackRoutePoint *fk_route_point(void *self)
{
    int i = ctrl_index(self);

    printf("  rp %s\n", nm(&cars[i]));
    return rps[i];
}

static float fk_oob(void *self)
{
    int i = ctrl_index(self);

    printf("  oob %s\n", nm(&cars[i]));
    return oobs[i];
}

// ------------------------------------------------------------ the dumps

static void dump_choice(const DrivingChoice *d, const char *tag)
{
    printf("  %s %d %s %d\n", tag, (int)d->Type, nm(d->pCar),
           (int)d->UseExtraLateralDistance);
}

static void dump_its(void)
{
    int k = index_in(choice.pCar, cars, sizeof cars[0], NCARS);
    const DriveTarget *t;

    if (k < 0)
        return;
    t = &cars[k].pCarDriver->MyDriveTarget;
    printf("  its pk %d %d %d\n", (int)t->WhichPointIPicked,
           (int)t->WhichPointIPickedCalculationTime,
           (int)t->WhichPointIPickedTime);
}

static void dump_target(const DriveTarget *t)
{
    int n = t->NumPoints, i;

    printf("  target n %d tt %d len %s last %d pk %d %d %d\n", n,
           (int)t->TType, fx(t->Length), (int)t->LastPointToScore,
           (int)t->WhichPointIPicked, (int)t->WhichPointIPickedCalculationTime,
           (int)t->WhichPointIPickedTime);
    for (i = 0; i < n && i < DRIVETARGET_MAX_POINTS; i++)
        printf("    %d %s %s %s r %d p %d l %d sp %s\n", i,
               fx(t->Points[i].x), fx(t->Points[i].y), fx(t->Points[i].z),
               (int)t->Route[i], (int)t->RoutePointNumber[i],
               (int)t->DrivingLine[i], fx(t->CalculatedSpeed[i]));
}

static void dump_fpl(void)
{
    int i;

    printf("  fpl %d\n", (int)fpl.NumPoints);
    for (i = 0; i < fpl.NumPoints && i < FUTUREPOINTLIST_MAX; i++) {
        const FuturePoint *p = &fpl.Points[i];

        printf("    %d r %d p %d l %d o %s x %d\n", i, (int)p->nRouteNumber,
               (int)p->nPointNumber, (int)p->nLine, fx(p->fOffset),
               (int)p->bCrossedSignpost);
    }
}

// The boxes written: up to the first whose a0 is still the fill. Only a
// position's x, y and z, as the checker's.
static void dump_obbs(void)
{
    int n = 0, i;

    while (n < DRIVETARGET_MAX_POINTS && written(&obbs[n].a0))
        n++;
    printf("  obbs %d\n", n);
    for (i = 0; i < n; i++) {
        const OBB *o = &obbs[i];

        // Two printfs: fx has 16 buffers, and a line is 19 values.
        printf("    %d %s %s %s | %s %s %s %s | %s %s %s %s", i,
               fx(o->Position.x), fx(o->Position.y), fx(o->Position.z),
               fx(o->A0.x), fx(o->A0.y), fx(o->A0.z), fx(o->A0.pad),
               fx(o->A1.x), fx(o->A1.y), fx(o->A1.z), fx(o->A1.pad));
        printf(" | %s %s %s %s | %s %s %s\n", fx(o->A2.x), fx(o->A2.y),
               fx(o->A2.z), fx(o->A2.pad), fx(o->a0), fx(o->a1), fx(o->a2));
    }
}

// A0's and A1's x and y, a0 and a1; the rest 0.
static void put_obb(OBB *o, char **v)
{
    memset(o, 0, sizeof *o);
    o->A0.x = fh(v[0]);
    o->A0.y = fh(v[1]);
    o->A1.x = fh(v[2]);
    o->A1.y = fh(v[3]);
    o->a0 = fh(v[4]);
    o->a1 = fh(v[5]);
}

// After a choice is made: the car the list's car leaves out, and the
// world's two counts.
static void dump_after(void)
{
    printf("  exclude %s\n", nm(car_ai_controller(list.MyCar)
                                    ->CarToExcludeFromCollisionPrediction));
    printf("  ids %u %u\n", (unsigned)world.CollisionPredictionID,
           (unsigned)world.PotentialDriveTargetID);
}

static void dump_walk(int got)
{
    printf("  adv %d %s %s n %d o %s x %d l %d\n", got, nm(walk.route),
           nm(walk.point), (int)walk.pn, fx(walk.off), walk.crossed,
           (int)walk.line);
}

// ------------------------------------------------------------ the world

static void reset(void)
{
    int i;

    memset(cars, 0, sizeof cars);
    memset(ctrls, 0, sizeof ctrls);
    memset(locs, 0, sizeof locs);
    memset(choices, 0, sizeof choices);
    memset(actions, 0, sizeof actions);
    memset(ctis, 0, sizeof ctis);
    memset(drivers, 0, sizeof drivers);
    memset(cdrivers, 0, sizeof cdrivers);
    memset(rps, 0, sizeof rps);
    memset(oobs, 0, sizeof oobs);
    memset(signs, 0, sizeof signs);
    memset(&race, 0, sizeof race);
    memset(bodies, 0, sizeof bodies);
    world.CollisionPredictionID = 0;
    world.PotentialDriveTargetID = 0;
    pCurrentWorld = &world;
    memset(TheTrackRouteManager.pTrackRoutes, 0,
           sizeof TheTrackRouteManager.pTrackRoutes);
    for (i = 0; i < NSIGNS; i++) {
        dec_take[i] = 0;
        dec_line[i] = -1;
    }
    fill(&list, sizeof list);
    fill(&loc, sizeof loc);
    fill(&choice, sizeof choice);
    fill(&other, sizeof other);
    fill(&fpl, sizeof fpl);
    fill(&lval, sizeof lval);
    fill(&walk, sizeof walk);
    fill(&target, sizeof target);
    WorldTimer = 0;
    pCurrentRace = &race;
    // As racecore.c starts them, so its initialisers are compared too.
    {
        static int saved;
        static float grace0, gap0, slowcar0, slowtraffic0, minspeed0;
        static int32_t traffic0, nlines0;

        if (!saved) {
            grace0 = StartOfRaceGracePeriod;
            gap0 = TimeBetweenCarsForGracePeriodExit;
            traffic0 = AITrafficTuningMode;
            slowcar0 = AISlowCarSpeed;
            slowtraffic0 = AISlowTrafficSpeed;
            minspeed0 = TryToDriveAroundCarMinSpeedForDrivingLine;
            nlines0 = AICarControllerNumDrivingLinesToConsider;
            saved = 1;
        }
        StartOfRaceGracePeriod = grace0;
        TimeBetweenCarsForGracePeriodExit = gap0;
        AITrafficTuningMode = traffic0;
        AISlowCarSpeed = slowcar0;
        AISlowTrafficSpeed = slowtraffic0;
        TryToDriveAroundCarMinSpeedForDrivingLine = minspeed0;
        AICarControllerNumDrivingLinesToConsider = nlines0;
    }
    WilliamsAITuningMode = 0;
    AIDriverSecondsToLookAhead = 2.0f;
    AIDriverDefaultLookAhead = 20.0f;
    SignpostArray = signs;
    NumSignposts = NSIGNS;
    gAISignPostDecisionFn = sign_decision;
}

static void set_global(const char *name, uint32_t v)
{
    float f;

    memcpy(&f, &v, 4);
    if (strcmp(name, "TIMER") == 0)
        WorldTimer = (int32_t)v;
    else if (strcmp(name, "GRACE") == 0)
        StartOfRaceGracePeriod = f;
    else if (strcmp(name, "GAP") == 0)
        TimeBetweenCarsForGracePeriodExit = f;
    else if (strcmp(name, "WILLIAMS") == 0)
        WilliamsAITuningMode = (int32_t)v;
    else if (strcmp(name, "SECS") == 0)
        AIDriverSecondsToLookAhead = f;
    else if (strcmp(name, "DEF") == 0)
        AIDriverDefaultLookAhead = f;
    else if (strcmp(name, "TRAFFIC") == 0)
        AITrafficTuningMode = (int32_t)v;
    else if (strcmp(name, "SLOWCAR") == 0)
        AISlowCarSpeed = f;
    else if (strcmp(name, "SLOWTRAFFIC") == 0)
        AISlowTrafficSpeed = f;
    else if (strcmp(name, "MINSPEED") == 0)
        TryToDriveAroundCarMinSpeedForDrivingLine = f;
    else if (strcmp(name, "NLINES") == 0)
        AICarControllerNumDrivingLinesToConsider = (int32_t)v;
    else {
        fprintf(stderr, "bad global %s\n", name);
        exit(2);
    }
}

static Car *car_ptr(const char *s)
{
    int k = atoi(s);

    return k >= 0 ? &cars[k] : NULL;
}

static TrackRoute *route_of(const char *s)
{
    int k = atoi(s);

    return k >= 0 ? &routes[k] : NULL;
}

static TrackRoutePoint *point_of(const char *r, const char *j)
{
    int k = atoi(r), i = atoi(j);

    if (k < 0 || i < 0)
        return NULL;
    return &routes[k].TrackRoutePointTable[i];
}

// The order of the checker's CAR_FIELDS.
enum {
    F_PX, F_PY, F_PZ, F_BX, F_BY, F_VMAG, F_DN, F_CLS, F_DTYPE, F_CTL,
    F_OOB, F_RPR, F_RPJ, F_CT, F_CC, F_CX, F_ACT, F_PL, F_NW, F_VX, F_VY,
    F_FS, NFIELDS
};

static void set_car(char **t)
{
    int k = atoi(t[1]);
    char **v = t + 2;
    Car *c = &cars[k];
    AICarController *a = &ctrls[k];
    int act = atoi(v[F_ACT]);

    c->DriverNumber = (int16_t)atoi(v[F_DN]);
    c->pCarTypeInfo = &ctis[k];
    ctis[k].CarClass = (int8_t)atoi(v[F_CLS]);
    c->MyDriver = &drivers[k];
    drivers[k].TheDriverType = (DriverType)atoi(v[F_DTYPE]);
    c->TheControlMode = (ControlMode)atoi(v[F_CTL]);
    c->pCarController = &a->Base;
    c->State.Position.x = fh(v[F_PX]);
    c->State.Position.y = fh(v[F_PY]);
    c->State.Position.z = fh(v[F_PZ]);
    c->State.BodyMatrix.v0.x = fh(v[F_BX]);
    c->State.BodyMatrix.v0.y = fh(v[F_BY]);
    c->State.VelocityMagnitude = fh(v[F_VMAG]);
    c->pPlayer = atoi(v[F_PL]) ? (Player *)(void *)players[k] : NULL;
    c->pCarDriver = &cdrivers[k];
    c->State.Velocity.x = fh(v[F_VX]);
    c->State.Velocity.y = fh(v[F_VY]);
    c->State.nWheelsTouchingGround = atoi(v[F_NW]);
    c->State.ForwardSpeed = fh(v[F_FS]);
    a->Base.pCar = c;
    a->Base._vtable = AICARCONTROLLER_VTABLE;
    a->CurrentDrivingLocation = &locs[k];
    a->CurrentDrivingChoice = &choices[k];
    fill(&a->CarToExcludeFromCollisionPrediction,
         sizeof a->CarToExcludeFromCollisionPrediction);
    a->CurrentAction = act >= 0 ? &actions[k] : NULL;
    actions[k].Type = act;
    choices[k].Type = atoi(v[F_CT]);
    choices[k].pCar = car_ptr(v[F_CC]);
    choices[k].UseExtraLateralDistance = atoi(v[F_CX]);
    oobs[k] = fh(v[F_OOB]);
    rps[k] = point_of(v[F_RPR], v[F_RPJ]);
}

static void set_choice(DrivingChoice *d, char **t)
{
    d->Type = atoi(t[1]);
    d->pCar = car_ptr(t[2]);
    d->UseExtraLateralDistance = atoi(t[3]);
}

// x y z rn j line sp, at the end of the target.
static void put_point(DriveTarget *d, char **v)
{
    int i = d->NumPoints;

    d->Points[i].x = fh(v[0]);
    d->Points[i].y = fh(v[1]);
    d->Points[i].z = fh(v[2]);
    d->Points[i].pad = 0.0f;
    d->Route[i] = (int8_t)atoi(v[3]);
    d->RoutePointNumber[i] = (int16_t)atoi(v[4]);
    d->DrivingLine[i] = (int8_t)atoi(v[5]);
    d->CalculatedSpeed[i] = fh(v[6]);
    d->NumPoints = (int8_t)(i + 1);
}

// ------------------------------------------------------------ the ops

static void op(char **t, int n)
{
    char c = t[0][0];

    if (c == 'U') {
        int k = atoi(t[1]), i;
        TrackRoute *r = &routes[k];
        int rn = atoi(t[3]);

        memset(r, 0, offsetof(TrackRoute, TrackRoutePointTable));
        r->Version = 1;
        r->RouteNumber = (int16_t)rn;
        r->Type = atoi(t[4]);
        r->NumPoints = atoi(t[2]);
        r->MaxPoints = r->NumPoints;
        for (i = 0; i < LINES; i++)
            r->DrivingLineInfoTable[i].Flags = wh(t[5 + i]);
        if (rn >= 0 && rn < TRACK_ROUTE_MAX_ROUTES)
            TheTrackRouteManager.pTrackRoutes[rn] = r;
        cur_route = r;
        cur_n = 0;
    } else if (c == 'P') {
        uint32_t w[28];
        int i;

        for (i = 0; i < 28; i++)
            w[i] = wh(t[1 + i]);
        memcpy(&cur_route->TrackRoutePointTable[cur_n++], w, sizeof w);
    } else if (c == 'K') {
        Signpost *s = &signs[atoi(t[1])];

        s->NewRoute = (uint8_t)atoi(t[2]);
        s->NewPoint = (uint16_t)atoi(t[3]);
    } else if (c == 'C') {
        if (n != 2 + NFIELDS) {
            fprintf(stderr, "car line with %d words\n", n);
            exit(2);
        }
        set_car(t);
    } else if (c == 'G') {
        set_global(t[1], wh(t[2]));
    } else if (c == 'Q') {
        int i = atoi(t[1]);

        dec_take[i] = atoi(t[2]);
        dec_line[i] = atoi(t[3]);
    } else if (c == 'R') {
        race.StartTime.PackedTime = wh(t[1]);
    } else if (c == 'N') {
        list.MyCar = car_ptr(t[1]);
        list.NumCarsInArray = atoi(t[2]);
        list.MyHalfSizeL = fh(t[3]);
        list.MyHalfSizeD = fh(t[4]);
    } else if (c == 'E') {
        NearbyCar *e = &list.Array[atoi(t[1])];

        e->Position.x = fh(t[2]);
        e->Position.y = fh(t[3]);
        e->Velocity.x = fh(t[4]);
        e->Velocity.y = fh(t[5]);
        e->ApparentHalfSizeL = fh(t[6]);
        e->ApparentHalfSizeD = fh(t[7]);
        e->TheCar = car_ptr(t[8]);
    } else if (c == 'D') {
        loc.pRoute = route_of(t[1]);
        loc.pRoutePoint = point_of(t[1], t[2]);
        loc.DrivingLine = atoi(t[3]);
        loc.LastRelaxedDrivingLineSwitchTime.PackedTime = wh(t[4]);
    } else if (c == 'T') {
        memset(&target, 0, sizeof target);
        target.TType = atoi(t[1]);
        target.Length = fh(t[2]);
        target.LastPointToScore = -1;
    } else if (c == 'Y') {
        put_point(&target, t + 1);
    } else if (c == 'H') {
        DriveTarget *d = &cdrivers[atoi(t[1])].MyDriveTarget;

        memset(d, 0, sizeof *d);
        d->TType = atoi(t[2]);
        d->Length = fh(t[3]);
        d->LastPointToScore = -1;
        d->WhichPointIPicked = (int8_t)atoi(t[4]);
        d->WhichPointIPickedCalculationTime = atoi(t[5]);
        d->WhichPointIPickedTime = atoi(t[6]);
    } else if (c == 'I') {
        put_point(&cdrivers[atoi(t[1])].MyDriveTarget, t + 2);
    } else if (c == 'X') {
        set_choice(&choice, t);
    } else if (c == 'O') {
        set_choice(&other, t);
    } else if (c == 'W') {
        walk.route = route_of(t[1]);
        walk.point = point_of(t[1], t[2]);
        walk.pn = atoi(t[3]);
        walk.line = atoi(t[4]);
        walk.off = fh(t[5]);
        walk.crossed = atoi(t[6]);
    } else if (c == 'F') {
        fill(&fpl, sizeof fpl);
        fpl.NumPoints = 0;
    } else if (c == 'a') {
        printf("  ctype %d\n", (int)drivingchoice_get_choice_type(atoi(t[1])));
    } else if (c == 'b') {
        printf("  dline %d\n", (int)drivingchoice_get_driving_line(
                                   atoi(t[1]), car_ptr(t[2])));
    } else if (c == 'c') {
        drivingchoice_set_choice(&choice, atoi(t[1]), car_ptr(t[2]),
                                 atoi(t[3]));
        dump_choice(&choice, "choice");
    } else if (c == 'd') {
        drivingchoice_set_choice_location(&choice, &loc);
        dump_choice(&choice, "choice");
    } else if (c == 'e') {
        drivingchoice_set_choice_choice(&choice, &other);
        dump_choice(&choice, "choice");
    } else if (c == 'f') {
        drivingchoice_clear(&choice);
        dump_choice(&choice, "choice");
    } else if (c == 'g') {
        printf("  valid %d\n", drivingchoice_is_valid(&choice, &loc, &list));
    } else if (c == 'h') {
        printf("  equal %d\n", drivingchoice_is_equal_to(&choice, &other));
    } else if (c == 'i') {
        printf("  room %d\n", drivingchoice_is_enough_room(
                                  &choice, &list.Array[atoi(t[1])], &list));
    } else if (c == 'j') {
        Car *car = car_ptr(t[1]);

        drivingchoice_fixup_car_to_exclude_from_collision_prediction(
            &choice, car, atoi(t[2]), &list);
        printf("  exclude %s\n",
               nm(car_ai_controller(car)->CarToExcludeFromCollisionPrediction));
    } else if (c == 'k') {
        printf("  side %d\n", drivingchoice_get_preferred_side_of_car(
                                  &list.Array[atoi(t[1])], &list, &loc));
    } else if (c == 'm') {
        futurepointlist_add(&fpl, atoi(t[1]), atoi(t[2]), atoi(t[3]),
                            fh(t[4]), atoi(t[5]));
        dump_fpl();
    } else if (c == 'n') {
        int got = drivingchoice_advance_point(
            &walk.route, &walk.point, &walk.pn, &walk.off, &walk.crossed,
            &walk.line, car_ai_controller(list.MyCar));

        dump_walk(got);
    } else if (c == 'o') {
        fill(&lval, sizeof lval);
        drivingchoice_get_route_points_to_use(&fpl, &target, &loc, &list,
                                              &lval);
        dump_fpl();
        printf("  L %s\n", fx(lval));
    } else if (c == 'p') {
        drivingchoice_get_route_points_up_to(&fpl, &loc, point_of(t[1], t[2]));
        dump_fpl();
    } else if (c == 'q') {
        printf("  speed %s\n", fx(drivingchoice_get_speed_back_to_line(
                                   &list, &loc, atoi(t[1]))));
    } else if (c == 'r') {
        lval = fh(t[1]);
        drivingchoice_reduce_current_l(&lval, atoi(t[2]), point_of(t[3], t[4]),
                                       atoi(t[5]), fh(t[6]), fh(t[7]),
                                       atoi(t[8]));
        printf("  l %s\n", fx(lval));
    } else if (c == 's') {
        drivingchoice_add_to_drive_target(fh(t[1]), &loc,
                                          &fpl.Points[atoi(t[2])], &target);
        dump_target(&target);
    } else if (c == 't') {
        int z = n > 3 ? atoi(t[3]) : 0;

        drivingchoice_fill_up_drive_target(z & 2 ? NULL : &target,
                                           z & 1 ? NULL : &loc,
                                           z & 4 ? NULL : &list, atoi(t[1]),
                                           atoi(t[2]));
        dump_target(&target);
        printf("  exclude %s\n", nm(car_ai_controller(list.MyCar)
                                        ->CarToExcludeFromCollisionPrediction));
    } else if (c == 'u') {
        printf("  grace %d\n",
               race_grace_period_is_active(pCurrentRace, car_ptr(t[1])));
    } else if (c == 'v' || c == 'w') {
        int got;

        if (c == 'v')
            got = drivingchoice_build_drive_target(&choice, &target, &loc,
                                                   &list, 1.0f, 2.0f,
                                                   atoi(t[1]));
        else
            got = drivingchoice_build_drive_target_around_car(
                &choice, &target, &list, 1.0f, &loc);
        printf("  built %d\n", got);
        dump_target(&target);
        printf("  exclude %s\n", nm(car_ai_controller(list.MyCar)
                                        ->CarToExcludeFromCollisionPrediction));
        dump_its();
    } else if (c == 'x') {
        bVector2 p;

        p.x = fh(t[1]);
        p.y = fh(t[2]);
        printf("  ahead %d\n", (int)futurepointlist_find_closest_point_ahead(
                                   &fpl, &p, atoi(t[3])));
    } else if (c == 'y') {
        int e = atoi(t[1]);

        printf("  clear %s\n", fx(drivingchoice_get_clearance(
                                   &list, e >= 0 ? &list.Array[e] : NULL,
                                   &fpl, atoi(t[2]))));
    } else if (c == 'z') {
        drivingchoice_do_smooth_offset_change(&fpl, &target, &list, atoi(t[1]),
                                              fh(t[2]), fh(t[3]), atoi(t[4]));
        dump_target(&target);
    } else if (c == 'M') {
        drivingchoice_make_drive_target_parallel_to_car(&choice, &target,
                                                        &list, &fpl, fh(t[1]));
        dump_target(&target);
        dump_its();
    } else if (c == 'A') {
        int k = atoi(t[1]);
        Car *car = &cars[k];
        CarCollisionBody *b = &bodies[k];

        car->State.Acceleration.x = fh(t[2]);
        car->State.Acceleration.y = fh(t[3]);
        car->State.Velocity.z = fh(t[4]);
        car->State.Angle = (uint16_t)atoi(t[5]);
        car->pDynamicCollisionBody = b;
        b->Dynamic.LocalBBMin.x = fh(t[6]);
        b->Dynamic.LocalBBMin.y = fh(t[7]);
        b->Dynamic.LocalBBMin.z = fh(t[8]);
        b->Dynamic.LocalBBMax.x = fh(t[9]);
        b->Dynamic.LocalBBMax.y = fh(t[10]);
        b->Dynamic.LocalBBMax.z = fh(t[11]);
    } else if (c == 'Z') {
        car_ai_controller(car_ptr(t[1]))->CarToExcludeFromCollisionPrediction =
            car_ptr(t[2]);
    } else if (c == 'S') {
        target.NumPoints = (int8_t)atoi(t[1]);
    } else if (c == '1') {
        int got;

        fill(outs, sizeof outs);
        got = ccp_interval_overlap(fh(t[1]), fh(t[2]), fh(t[3]), fh(t[4]),
                                   &outs[0], &outs[1]);
        printf("  ovl %d %s %s\n", got, fx(outs[0]), fx(outs[1]));
    } else if (c == '2') {
        fill(outs, sizeof outs);
        ccp_time_interval_for_separating_axis(fh(t[1]), fh(t[2]), fh(t[3]),
                                              &outs[0], &outs[1]);
        printf("  tisa %s %s\n", fx(outs[0]), fx(outs[1]));
    } else if (c == '3') {
        bVector3 d, v;

        put_obb(&obb_a, t + 1);
        put_obb(&obb_b, t + 7);
        d.x = fh(t[13]);
        d.y = fh(t[14]);
        d.z = d.pad = 0.0f;
        v.x = fh(t[15]);
        v.y = fh(t[16]);
        v.z = v.pad = 0.0f;
        printf("  when %s\n",
               fx(ccp_when_will_overlap_occur_2d(&obb_a, &obb_b, &d, &v)));
    } else if (c == '4') {
        int z = atoi(t[4]);
        int k = atoi(t[1]);
        DriveTarget *d = k < 0 ? &target : &cdrivers[k].MyDriveTarget;

        fill(obbs, sizeof obbs);
        ccp_make_obbs_for_drive_target(z & 1 ? NULL : d, z & 2 ? NULL : obbs,
                                       car_ptr(t[2]), fh(t[3]));
        dump_obbs();
    } else if (c == '5') {
        printf("  stopped %d\n", ccp_is_this_car_stopped_directly_in_front_of_me(
                                      &list.Array[atoi(t[1])], &list));
    } else if (c == '6') {
        int got;

        fill(outs, sizeof outs);
        got = ccp_will_i_hit_this_car(&target, &loc, list.MyCar, car_ptr(t[1]),
                                      fh(t[2]), &outs[0]);
        printf("  will %d %s\n", got, fx(outs[0]));
    } else if (c == '7') {
        Car *got;

        fill(outs, sizeof outs);
        got = ccp_who_will_this_drive_target_hit(
            &target, &list, atoi(t[2]) & 1 ? NULL : &loc, fh(t[1]), &outs[0]);
        printf("  who %s %s id %u\n", nm(got), fx(outs[0]),
               (unsigned)world.CollisionPredictionID);
    } else if (c == '8') {
        float score, hitTime;
        Car *hitCar;
        int got;

        fill(&score, sizeof score);
        fill(&hitTime, sizeof hitTime);
        fill(&hitCar, sizeof hitCar);
        got = drivingchoice_is_driveable(&choice, &target, atoi(t[1]), &score,
                                         &hitCar, &hitTime, &loc, &list, 1.0f,
                                         fh(t[3]), 2.0f, atoi(t[2]));
        printf("  drive %d %s %s %s\n", got, fx(score), nm(hitCar),
               fx(hitTime));
        dump_target(&target);
        dump_after();
    } else if (c == '9') {
        int found = atoi(t[3]), bout, got;
        float bscore = fh(t[4]), rtime = fh(t[5]), htime;
        Car *hcar;

        fill(&bout, sizeof bout);
        fill(&htime, sizeof htime);
        fill(&hcar, sizeof hcar);
        fill(&best_ch, sizeof best_ch);
        fill(&round_ch, sizeof round_ch);
        fill(&target2, sizeof target2);
        fill(&target3, sizeof target3);
        got = drivingchoice_try_choice(&choice, atoi(t[1]), fh(t[2]), &loc,
                                       &list, 3.0f, &found, &target, &best_ch,
                                       &target2, &bout, &bscore, &round_ch,
                                       &target3, &rtime, &hcar, &htime,
                                       car_ptr(t[6]));
        printf("  try %d found %d bout %08x score %s round %s hit %s %s\n",
               got, found, (unsigned)bout, fx(bscore), fx(rtime), nm(hcar),
               fx(htime));
        dump_choice(&best_ch, "best");
        dump_choice(&round_ch, "round");
        dump_target(&target);
        dump_target(&target2);
        dump_target(&target3);
        dump_after();
    } else if (c == '0' || c == 'V') {
        int out = (int)wh(t[c == 'V' ? 4 : 3]), got;

        if (c == '0') {
            got = drivingchoice_make_new_choice(&choice, &target, &loc, &list,
                                                fh(t[1]), 3.0f, &out,
                                                atoi(t[2]));
            printf("  new %d out %08x\n", got, (unsigned)out);
        } else {
            got = drivingchoice_try_to_drive_around_car(
                &choice, &target, &out, &list.Array[atoi(t[1])], &loc, &list,
                1.0f, fh(t[2]), 3.0f, atoi(t[3]));
            printf("  around %d out %08x\n", got, (unsigned)out);
        }
        dump_choice(&choice, "choice");
        dump_target(&target);
        dump_after();
    } else {
        fprintf(stderr, "bad op %s\n", t[0]);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[8192];
    FILE *f;

    if (argc != 2) {
        fprintf(stderr, "usage: drivingchoice_test SCRIPT\n");
        return 2;
    }
    drivetarget_static_init();
    memset(ctl_vt, 0, sizeof ctl_vt);
    ctl_vt[VT_SLOT(CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT)].fn =
        (VtFn)fk_route_point;
    ctl_vt[VT_SLOT(CARCONTROLLER_VT_GET_AMOUNT_OUT_OF_BOUNDS)].fn =
        (VtFn)fk_oob;
    vt_install(AICARCONTROLLER_VTABLE, ctl_vt, CARCONTROLLER_VT_ENTRIES);

    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    while (fgets(line, sizeof line, f) != NULL) {
        char *t[64];
        int n = 0;
        char *s;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        if (line[0] == 'B') {
            printf("%s\n", line);
            reset();
            continue;
        }
        if (strchr("CKPU", line[0]) == NULL)
            printf("> %.48s\n", line);
        for (s = strtok(line, " "); s != NULL && n < 64; s = strtok(NULL, " "))
            t[n++] = s;
        op(t, n);
    }
    fclose(f);
    return 0;
}
