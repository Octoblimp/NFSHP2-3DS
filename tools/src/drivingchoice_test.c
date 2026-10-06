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
#include "carcontroller.h"
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

// racecore.c's destructor and boundary code reach these; nothing here
// calls either.
void (*gWorldObjectDeleteFn)(WorldObject *o);

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

static void dump_target(void)
{
    const DriveTarget *t = &target;
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
    memset(rps, 0, sizeof rps);
    memset(oobs, 0, sizeof oobs);
    memset(signs, 0, sizeof signs);
    memset(&race, 0, sizeof race);
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
        static float grace0, gap0;

        if (!saved) {
            grace0 = StartOfRaceGracePeriod;
            gap0 = TimeBetweenCarsForGracePeriodExit;
            saved = 1;
        }
        StartOfRaceGracePeriod = grace0;
        TimeBetweenCarsForGracePeriodExit = gap0;
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
    F_OOB, F_RPR, F_RPJ, F_CT, F_CC, F_CX, F_ACT, NFIELDS
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
        int i = target.NumPoints;

        target.Points[i].x = fh(t[1]);
        target.Points[i].y = fh(t[2]);
        target.Points[i].z = fh(t[3]);
        target.Points[i].pad = 0.0f;
        target.Route[i] = (int8_t)atoi(t[4]);
        target.RoutePointNumber[i] = (int16_t)atoi(t[5]);
        target.DrivingLine[i] = (int8_t)atoi(t[6]);
        target.CalculatedSpeed[i] = fh(t[7]);
        target.NumPoints = (int8_t)(i + 1);
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
        dump_target();
    } else if (c == 't') {
        int z = n > 3 ? atoi(t[3]) : 0;

        drivingchoice_fill_up_drive_target(z & 2 ? NULL : &target,
                                           z & 1 ? NULL : &loc,
                                           z & 4 ? NULL : &list, atoi(t[1]),
                                           atoi(t[2]));
        dump_target();
        printf("  exclude %s\n", nm(car_ai_controller(list.MyCar)
                                        ->CarToExcludeFromCollisionPrediction));
    } else if (c == 'u') {
        printf("  grace %d\n",
               race_grace_period_is_active(pCurrentRace, car_ptr(t[1])));
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
