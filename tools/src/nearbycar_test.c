// Host harness for 3DS Files/source/nearbycar.c and drivinglocation.c,
// what an AI car knows of the cars around it and where it drives. Runs the
// op script tools/nearbycar_check.py writes and prints the transcript it
// diffs against the retail image, run in mipsemu over the same script.
//
// The harness owns the world, the cars and their records, the routes, the
// acceleration tables' contents and the belt mover's gravity (each car's,
// by its mover). Everything else is the port's own: car.c, carstate.c,
// carinfo.c, drivetarget.c, trackpath.c, table.c and the maths.
//
// A float prints as its bits, every NaN as "nan", and a pointer by what it
// points at. The ops and every line's format are the checker's.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "car.h"
#include "carinfo.h"
#include "cartypeinfo.h"
#include "collisionbody.h"
#include "drivetarget.h"
#include "drivinglocation.h"
#include "nearbycar.h"
#include "trackpath.h"
#include "trackroute.h"
#include "world.h"

#define NCARS   32
#define NROUTES 4
#define LINES   21
#define PAT     0xa5

// The world clock's, here rather than linked from realtime.c, which would
// bring the joylog in behind it (as tools/src/realdriver_test.c).
int32_t WorldTimer;
int32_t WorldTimeFrames;
float   WorldTimeElapsed;

static World world;
static Car cars[NCARS];
static CarTypeInfo ctis[NCARS];
static RideInfo rides[NCARS];
static CarCollisionBody bodies[NCARS];
static char movers[NCARS][16];
static float belts[NCARS];
static char player_dummy[16];
static TrackRoute routes[NROUTES];
static NearbyCarList list;
static NearbyCar scratch;
static DrivingInformation di;
static DrivingLocation loc;

static TrackRoute *cur_route;
static int cur_n;

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
    for (i = 0; i < NCARS; i++) {
        if (p == &cars[i]) {
            sprintf(b, "c%d", i);
            return b;
        }
    }
    if (p == &scratch)
        return "s";
    for (i = 0; i < NEARBYCARLIST_MAX; i++) {
        if (p == &list.Array[i]) {
            sprintf(b, "e%d", i);
            return b;
        }
    }
    for (i = 0; i < NROUTES; i++) {
        const TrackRoute *r = &routes[i];

        if (p == r) {
            sprintf(b, "R%d", i);
            return b;
        }
        if ((const char *)p >= (const char *)r->TrackRoutePointTable
            && (const char *)p < (const char *)(r + 1)) {
            ptrdiff_t off = (const char *)p
                            - (const char *)r->TrackRoutePointTable;

            if (off % (ptrdiff_t)sizeof(TrackRoutePoint) == 0) {
                sprintf(b, "R%d:%d", i,
                        (int)(off / (ptrdiff_t)sizeof(TrackRoutePoint)));
                return b;
            }
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

// ------------------------------------------------------------ the stub

static float belt_gravity(CarMover *m)
{
    int i;

    for (i = 0; i < NCARS; i++)
        if ((char *)m == movers[i])
            return belts[i];
    fprintf(stderr, "belt gravity of an unknown mover\n");
    exit(2);
}

// ------------------------------------------------------------ the dumps

static void dump_list(const NearbyCarList *l)
{
    int i;

    printf("  list me %s n %d hl %s hd %s\n", nm(l->MyCar),
           (int)l->NumCarsInArray, fx(l->MyHalfSizeL), fx(l->MyHalfSizeD));
    for (i = 0; i < NEARBYCARLIST_MAX; i++) {
        const NearbyCar *c = &l->Array[i];

        printf("    %d %s %s %s %s %s %s %s\n", i, fx(c->Position.x),
               fx(c->Position.y), fx(c->Velocity.x), fx(c->Velocity.y),
               fx(c->ApparentHalfSizeL), fx(c->ApparentHalfSizeD),
               nm(c->TheCar));
    }
}

static void dump_loc(const DrivingLocation *d, const char *tag)
{
    printf("  %s %s %s line %d t %08x\n", tag, nm(d->pRoute),
           nm(d->pRoutePoint), (int)d->DrivingLine,
           (unsigned)d->LastRelaxedDrivingLineSwitchTime.PackedTime);
}

// ------------------------------------------------------------ the world

static void link_cars(char **t, int n)
{
    void *prev = &world.CarList;
    int i;

    world.CarList.next = &world.CarList;
    world.CarList.prev = &world.CarList;
    for (i = 0; i < n; i++) {
        Car *c = &cars[atoi(t[i])];

        if (prev == &world.CarList)
            world.CarList.next = c;
        else
            ((Car *)prev)->Link.next = (CarNode *)c;
        c->Link.prev = (CarNode *)prev;
        prev = c;
    }
    if (prev == &world.CarList) {
        world.CarList.prev = &world.CarList;
    } else {
        ((Car *)prev)->Link.next = (CarNode *)&world.CarList;
        world.CarList.prev = prev;
    }
}

static void reset(void)
{
    memset(&world, 0, sizeof world);
    memset(cars, 0, sizeof cars);
    pCurrentWorld = &world;
    link_cars(NULL, 0);
    fill(&list, sizeof list);
    fill(&scratch, sizeof scratch);
    fill(&di, sizeof di);
    fill(&loc, sizeof loc);
    TrafficDriverLookaheadFactor = 3.0f;
    AIActionPassMaxTimeAheadToMakeAttempt = 3.0f;
    AIDriverSecondsToLookAhead = 2.0f;
    AIDriverDefaultLookAhead = 20.0f;
    CameraFollowThisCarInstead = -1;
    HighlightDrivingLineInRouteNumber = -1;
    HighlightDrivingLineNumber = -1;
    WorldTimer = 0;
    TheTrackPathManager.TrackLength = 2000.0f;
    gBeltMoverGravityFn = belt_gravity;
}

static void set_global(const char *name, uint32_t v)
{
    float f;

    memcpy(&f, &v, 4);
    if (strcmp(name, "TDLF") == 0)
        TrafficDriverLookaheadFactor = f;
    else if (strcmp(name, "PASS") == 0)
        AIActionPassMaxTimeAheadToMakeAttempt = f;
    else if (strcmp(name, "SECS") == 0)
        AIDriverSecondsToLookAhead = f;
    else if (strcmp(name, "DEF") == 0)
        AIDriverDefaultLookAhead = f;
    else if (strcmp(name, "CAM") == 0)
        CameraFollowThisCarInstead = (int32_t)v;
    else if (strcmp(name, "HROUTE") == 0)
        HighlightDrivingLineInRouteNumber = (int32_t)v;
    else if (strcmp(name, "HLINE") == 0)
        HighlightDrivingLineNumber = (int32_t)v;
    else if (strcmp(name, "TIMER") == 0)
        WorldTimer = (int32_t)v;
    else if (strcmp(name, "LEN") == 0)
        TheTrackPathManager.TrackLength = f;
    else {
        fprintf(stderr, "bad global %s\n", name);
        exit(2);
    }
}

// The order of the checker's CAR_FIELDS.
enum {
    F_PX, F_PY, F_PZ, F_VX, F_VY, F_VZ, F_VW, F_AX, F_AY, F_AZ,
    F_BX, F_BY, F_BZ, F_ANGLE, F_FWD, F_VMAG, F_BOOST, F_DRAFT, F_REND,
    F_POOF, F_DAT, F_CTL, F_MOV, F_TYPE, F_DRAG, F_LIMITER, F_MASS,
    F_PLAYER, F_MINX, F_MINY, F_MINZ, F_MAXX, F_MAXY, F_MAXZ, F_BELT,
    NFIELDS
};

static void set_car(char **t)
{
    int k = atoi(t[1]);
    char **v = t + 2;
    Car *c = &cars[k];
    CarCollisionBody *b = &bodies[k];

    c->pCarTypeInfo = &ctis[k];
    c->pRideInfo = &rides[k];
    c->pPlayer = wh(v[F_PLAYER]) ? (Player *)player_dummy : NULL;
    c->TheControlMode = (ControlMode)wh(v[F_CTL]);
    c->TheMovementMode = (MovementMode)wh(v[F_MOV]);
    c->pCarMover = (CarMover *)movers[k];
    c->pDynamicCollisionBody = b;
    c->State.Position.x = fh(v[F_PX]);
    c->State.Position.y = fh(v[F_PY]);
    c->State.Position.z = fh(v[F_PZ]);
    c->State.Velocity.x = fh(v[F_VX]);
    c->State.Velocity.y = fh(v[F_VY]);
    c->State.Velocity.z = fh(v[F_VZ]);
    c->State.Velocity.pad = fh(v[F_VW]);
    c->State.Acceleration.x = fh(v[F_AX]);
    c->State.Acceleration.y = fh(v[F_AY]);
    c->State.Acceleration.z = fh(v[F_AZ]);
    c->State.BodyMatrix.v0.x = fh(v[F_BX]);
    c->State.BodyMatrix.v0.y = fh(v[F_BY]);
    c->State.BodyMatrix.v0.z = fh(v[F_BZ]);
    c->State.Angle = (uint16_t)wh(v[F_ANGLE]);
    c->State.ForwardSpeed = fh(v[F_FWD]);
    c->State.VelocityMagnitude = fh(v[F_VMAG]);
    c->State.BoostFactor = fh(v[F_BOOST]);
    c->State.MatrixValid = 0;
    c->DraftFactor = fh(v[F_DRAFT]);
    c->RenderingEnabled = (int8_t)wh(v[F_REND]);
    c->bPoofed = (int32_t)wh(v[F_POOF]);
    c->TheTrackPathCoordinate.DistanceAroundTrack = fh(v[F_DAT]);
    rides[k].Type = (int32_t)wh(v[F_TYPE]);
    ctis[k].Aero.Drag = fh(v[F_DRAG]);
    ctis[k].Control.SpeedLimiter = fh(v[F_LIMITER]);
    ctis[k].Body.Mass = fh(v[F_MASS]);
    b->Dynamic.LocalBBMin.x = fh(v[F_MINX]);
    b->Dynamic.LocalBBMin.y = fh(v[F_MINY]);
    b->Dynamic.LocalBBMin.z = fh(v[F_MINZ]);
    b->Dynamic.LocalBBMin.pad = 0.0f;
    b->Dynamic.LocalBBMax.x = fh(v[F_MAXX]);
    b->Dynamic.LocalBBMax.y = fh(v[F_MAXY]);
    b->Dynamic.LocalBBMax.z = fh(v[F_MAXZ]);
    b->Dynamic.LocalBBMax.pad = 0.0f;
    belts[k] = fh(v[F_BELT]);
}

static void set_table(char **t)
{
    int k = atoi(t[1]), n = atoi(t[2]), i;
    AccelerationTable *a = &TheCarTypeAccelerationTable[k];

    memset(a, 0, sizeof *a);
    for (i = 0; i < n; i++)
        a->Data[i] = fh(t[6 + i]);
    a->mTable.pTable = a->Data;
    a->mTable.NumEntries = n;
    a->mTable.MinArg = fh(t[3]);
    a->mTable.MaxArg = fh(t[4]);
    a->mTable.IndexMultiplier = fh(t[5]);
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

static NearbyCar *entry(const char *s)
{
    if (strcmp(s, "s") == 0)
        return &scratch;
    if (strcmp(s, "n") == 0)
        return NULL;
    return &list.Array[atoi(s)];
}

static int past(const char *s)
{
    return strcmp(s, "s") != 0 && strcmp(s, "n") != 0
           && atoi(s) >= list.NumCarsInArray;
}

static Car *car_ptr(const char *s)
{
    int k = atoi(s);

    return k >= 0 ? &cars[k] : NULL;
}

// ------------------------------------------------------------ the ops

static void op(char **t, int n)
{
    char c = t[0][0];

    if (c == 'A') {
        set_table(t);
    } else if (c == 'G') {
        set_global(t[1], wh(t[2]));
    } else if (c == 'C') {
        if (n != 2 + NFIELDS) {
            fprintf(stderr, "car line with %d words\n", n);
            exit(2);
        }
        set_car(t);
    } else if (c == 'L') {
        link_cars(t + 1, n - 1);
    } else if (c == 'R') {
        fill(&list, sizeof list);
    } else if (c == 'N') {
        list.MyCar = car_ptr(t[1]);
        nearbycarlist_build_array(&list, atoi(t[2]) ? &loc : NULL, 1.0f);
        dump_list(&list);
    } else if (c == 'M') {
        dump_list(&list);
    } else if (c == 'I') {
        Car *car = car_ptr(t[1]);
        int32_t i = nearbycarlist_get_cars_index_in_array(&list, car);
        NearbyCar *nb = nearbycarlist_get_nearby_car(&list, car);
        NearbyCar *ah = nearbycarlist_get_car_ahead(&list, car);

        printf("  index %d nearby %s ahead %s\n", (int)i, nm(nb), nm(ah));
    } else if (c == 'Q') {
        scratch.Position.x = fh(t[1]);
        scratch.Position.y = fh(t[2]);
        scratch.Velocity.x = fh(t[3]);
        scratch.Velocity.y = fh(t[4]);
        scratch.ApparentHalfSizeL = fh(t[5]);
        scratch.ApparentHalfSizeD = fh(t[6]);
        scratch.TheCar = car_ptr(t[7]);
    } else if (c == 'Y') {
        if (past(t[1])) {
            printf("  skip\n");
            return;
        }
        printf("  care %d\n", ai_do_we_care_about_this_car(entry(t[1]), &list));
    } else if (c == 'K') {
        if (past(t[1])) {
            printf("  skip\n");
            return;
        }
        printf("  catch %d\n",
               ai_can_i_catch_this_car(entry(t[1]), car_ptr(t[2]), fh(t[3]),
                                       atoi(t[4])));
    } else if (c == 'X') {
        printf("  max %s\n",
               fx(ai_calculate_max_acceleration(car_ptr(t[1]), fh(t[2]))));
    } else if (c == 'U') {
        int k = atoi(t[1]);
        TrackRoute *r = &routes[k];

        memset(r, 0, offsetof(TrackRoute, TrackRoutePointTable));
        r->Version = 1;
        r->RouteNumber = (int16_t)atoi(t[3]);
        r->NumPoints = atoi(t[2]);
        r->MaxPoints = r->NumPoints;
        cur_route = r;
        cur_n = 0;
    } else if (c == 'P') {
        uint32_t w[28];
        int i;

        for (i = 0; i < 28; i++)
            w[i] = wh(t[1 + i]);
        memcpy(&cur_route->TrackRoutePointTable[cur_n++], w, sizeof w);
    } else if (c == 'D') {
        loc.pRoute = route_of(t[1]);
        loc.pRoutePoint = point_of(t[1], t[2]);
        loc.DrivingLine = atoi(t[3]);
        loc.LastRelaxedDrivingLineSwitchTime.PackedTime = wh(t[4]);
    } else if (c == 'V') {
        printf("  curve %s\n", fx(ai_get_current_curvature_of_driving_line(
                                   &loc)));
    } else if (c == 'H') {
        ai_highlight_driving_line(&loc, atoi(t[1]));
        printf("  highlight %d %d\n", (int)HighlightDrivingLineInRouteNumber,
               (int)HighlightDrivingLineNumber);
    } else if (c == 'S') {
        drivinglocation_set_route(&loc, route_of(t[1]), point_of(t[1], t[2]),
                                  atoi(t[3]), atoi(t[4]));
        dump_loc(&loc, "loc");
    } else if (c == 'T') {
        drivinglocation_set_route_point(&loc, point_of(t[1], t[2]));
        dump_loc(&loc, "loc");
    } else if (c == 'J') {
        drivinglocation_set_driving_line(&loc, atoi(t[1]), atoi(t[2]));
        dump_loc(&loc, "loc");
    } else if (c == 'Z') {
        drivinglocation_set_relaxed_switch(&loc, atoi(t[1]));
        dump_loc(&loc, "loc");
    } else if (c == 'E') {
        float left = drivinglocation_get_num_seconds_left_in_relaxed_switch(
            &loc);
        int got = drivinglocation_are_we_in_a_relaxed_switch(&loc);

        printf("  left %s relaxed %d\n", fx(left), got);
    } else if (c == 'O') {
        drivinglocation_clear(&loc);
        dump_loc(&loc, "loc");
    } else if (c == 'F') {
        drivinginformation_clear(&di);
        printf("  di me %s n %d hl %s hd %s\n", nm(di.MyNearbyCarList.MyCar),
               (int)di.MyNearbyCarList.NumCarsInArray,
               fx(di.MyNearbyCarList.MyHalfSizeL),
               fx(di.MyNearbyCarList.MyHalfSizeD));
        dump_loc(&di.MyDrivingLocation, "diloc");
        printf("  choice %d %s %d\n", (int)di.MyDrivingChoice.Type,
               nm(di.MyDrivingChoice.pCar),
               (int)di.MyDrivingChoice.UseExtraLateralDistance);
    } else if (c == 'W') {
        nearbycarlist_clear_array(&list);
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
        fprintf(stderr, "usage: nearbycar_test SCRIPT\n");
        return 2;
    }
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
        if (strchr("ACPU", line[0]) == NULL)
            printf("> %.48s\n", line);
        for (s = strtok(line, " "); s != NULL && n < 64; s = strtok(NULL, " "))
            t[n++] = s;
        op(t, n);
    }
    fclose(f);
    return 0;
}
