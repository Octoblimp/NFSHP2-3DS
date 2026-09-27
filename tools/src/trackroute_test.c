// Host harness for 3DS Files/source/trackroute.c (and the part of
// trackpath.c it leans on). Prints a transcript that
// tools/trackroute_check.py diffs line by line against an independent model
// built from the ELF.
//
// Same rules as the other harnesses: every float is a float32 printed with
// %.9g, so a one-ulp disagreement is a changed line rather than something a
// tolerance swallows.
//
// Three things this file has to be careful about, all of them properties of
// the object rather than of the test:
//
//   * A TrackRoute is 115752 bytes. They live in static storage here, never
//     on the stack.
//   * Nothing may be printed that is a pointer. The routes are on a circular
//     list whose head is inside the manager, so the transcript names list
//     members by route number and never by address.
//   * TrackRoutePoint's constructor deliberately leaves fields alone. To
//     show that, the harness fills the storage with a known pattern first
//     and prints what survived -- so the pattern has to be part of the
//     transcript's contract, and the model reproduces it.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "trackpath.h"
#include "trackroute.h"

// ------------------------------------------------------------------- output

static void ppoint(const char *tag, const TrackRoutePoint *p)
{
    printf("  %s pos %.9g %.9g elev %.9g dir %.9g %.9g len %.9g\n",
           tag, p->Position.x, p->Position.y, p->Elevation,
           p->Direction.x, p->Direction.y, p->Length);
    printf("    w %.9g %.9g slope %.9g %.9g dist %.9g bits %08lx\n",
           p->LeftWidth, p->RightWidth, p->BankSlope, p->ForwardSlope,
           p->DistanceAroundTrack, (unsigned long)p->Bits);
    printf("    sign %lu rb %lu rt %lu terr %lu posted %d nohel %d pb %d"
           " rnum %u\n",
           (unsigned long)trpoint_sign_number(p),
           (unsigned long)trpoint_road_block_number(p),
           (unsigned long)trpoint_radar_trap_number(p),
           (unsigned long)trpoint_terrain_type(p),
           trpoint_is_posted(p), (p->Bits & TRP_NO_HELISHEET) != 0,
           (p->Bits & TRP_POSTED_BACKWARDS) != 0, (unsigned)p->RouteNumber);
}

static void plines(const TrackRoutePoint *p)
{
    int i;
    printf("    off");
    for (i = 0; i < TRP_NUM_DRIVING_LINES; i++)
        printf(" %d", (int)p->DrivingLineOffsets[i]);
    printf("\n    spd");
    for (i = 0; i < TRP_NUM_DRIVING_LINES; i++)
        printf(" %u", (unsigned)p->DrivingLineSpeeds[i]);
    printf("\n");
}

static void proute(const char *tag, const TrackRoute *r)
{
    int i;
    printf("route %s n %d ver %d type %d pts %d max %d flags %08lx tune %d\n",
           tag, (int)r->RouteNumber, (int)r->Version, (int)r->Type,
           r->NumPoints, r->MaxPoints, (unsigned long)r->Flags,
           r->CurrentlyTuningDrivingLine);
    printf("  span %.9g %.9g bbox %.9g %.9g %.9g %.9g\n",
           r->fStartDistance, r->fEndDistance, r->BBoxMin.x, r->BBoxMin.y,
           r->BBoxMax.x, r->BBoxMax.y);
    for (i = 0; i < TRP_NUM_DRIVING_LINES; i++) {
        const DrivingLineInfo *d = &r->DrivingLineInfoTable[i];
        printf("  line %2d flags %08lx time %.9g name %.20s\n", i,
               (unsigned long)d->Flags, d->LineTime, d->DriverName);
    }
    for (i = 0; i < r->NumPoints; i++) {
        char lbl[16];
        sprintf(lbl, "p%d", i);
        ppoint(lbl, &r->TrackRoutePointTable[i]);
    }
}

// Route numbers in list order. Never an address: the routes live inside the
// chunk buffer and the transcript has to be the same on any host.
static void plist(const char *tag, TrackRoute *const *list, int n)
{
    int i;
    printf("  list %s:", tag);
    for (i = 0; i < n; i++) printf(" %d", (int)list[i]->RouteNumber);
    printf("\n");
}

static void plists(TrackRouteManager *m)
{
    plist("racing", m->Racing, m->NumRacing);
    plist("traffic", m->Traffic, m->NumTraffic);
}

// A disc sign's Distance is whatever the tools left there until
// SetDistances fills it, and on retail TRACKB21 two are NaNs. A NaN prints
// `-nan` here and `nan` in Python, so it is spelled once, by hand.
static const char *g9(char *buf, float x)
{
    if (x != x) return "nan";
    sprintf(buf, "%.9g", x);
    return buf;
}

static void psigns(const char *tag)
{
    uint32_t i;
    char     d[32];
    printf("signposts %s n %lu\n", tag, (unsigned long)NumSignposts);
    for (i = 0; i < NumSignposts; i++) {
        const Signpost *s = &SignpostArray[i];
        printf("  %2lu route %u point %u sign %u back %d nostake %d"
               " hairpin %d cloak %d dist %s hint %ld\n",
               (unsigned long)i, (unsigned)s->NewRoute, (unsigned)s->NewPoint,
               (unsigned)(s->Flags & SIGNPOST_SIGN_MASK),
               (s->Flags & SIGNPOST_BACKWARDS) != 0,
               (s->Flags & SIGNPOST_NO_STAKEOUT) != 0,
               (s->Flags & SIGNPOST_HAIRPIN) != 0,
               (s->Flags & SIGNPOST_CLOAKED) != 0, g9(d, s->Distance),
               (long)s->AIHint);
    }
}

// ------------------------------------------------------------------ the rng
//
// The same LCG the other harnesses use; every step is exact in float32.

static uint32_t rngState;

static void rseed(uint32_t s)
{
    rngState = s;
}

static float frand(float scale)
{
    float u;

    rngState = rngState * 1103515245u + 12345u;
    u = (float)(int32_t)(rngState >> 8) * (1.0f / 8388608.0f) - 1.0f;
    return u * scale;
}

// ------------------------------------------------------------- the seam
//
// QuickSpline is not ported, so TrackPathCoordinate cannot measure anything.
// This stands in for it with a closed form built only out of add, multiply
// and compare, so it is bit-identical in the model: a linear ramp across the
// plane, wrapped into [0, TrackLength). It wraps often enough over the test
// routes to drive SetFirstAndLast's two-bucket path.

static float test_distance(const bVector2 *p)
{
    float len = TheTrackPathManager.TrackLength;
    float t;
    int   guard;

    if (!(len > 0.0f)) return 0.0f;
    t = p->x * 0.5f + p->y * 0.25f;
    for (guard = 0; guard < 64 && t < 0.0f; guard++) t += len;
    for (guard = 0; guard < 64 && !(t < len); guard++) t -= len;
    return t;
}

// -------------------------------------------------------------- storage

#define NROUTES 5
static TrackRoute gRoutes[NROUTES];

// Enough for the truncated memory images the loader scenario builds.
#define CHUNKCAP 65536
static uint8_t gChunk[CHUNKCAP];

static Signpost gSigns[8];

// Fill a route's storage with a recognisable pattern, so the fields the
// constructors deliberately skip show up in the transcript instead of
// hiding behind whatever the loader's memory happened to hold.
//
// Bit 6 of every fourth byte is cleared, which caps the exponent of any
// float read out of the fill at 0x7f and so keeps it finite. Without that
// the pattern makes NaNs, and a NaN in the transcript is not portable: this
// libc prints `-nan`, MSVC prints `-nan(ind)` and Python prints `nan`, so
// the diff would report a disagreement that is only about spelling.
static void dirty(void *p, size_t n, uint8_t seed)
{
    uint8_t *b = (uint8_t *)p;
    size_t   i;
    for (i = 0; i < n; i++) {
        b[i] = (uint8_t)(seed + (uint8_t)(i * 37u));
        if ((i & 3) == 3) b[i] &= 0xbf;
    }
}

// A route of `n` points along a curve, built the way the editor builds one.
static void build_route(TrackRoute *r, int number, int n, float ox, float oy,
                        float turn)
{
    int i;

    troute_init(r, number);
    for (i = 0; i < n; i++) {
        bVector2 p;
        float    t = (float)i;
        float    lw, rw;
        p.x = ox + t * 20.0f + t * t * turn;
        p.y = oy + t * 6.0f - t * t * turn * 0.5f;
        // Sequenced deliberately. Two calls to the same generator inside one
        // argument list would be drawn in whichever order the compiler felt
        // like, and the transcript has to be the same everywhere.
        lw = 6.0f + frand(1.0f);
        rw = 7.0f + frand(1.0f);
        troute_add_point(r, &p, t * 1.5f, lw, rw);
    }
}

// ---------------------------------------------------------------- scenarios

static void scenario_point(void)
{
    static TrackRoutePoint p;
    bVector2 o2;
    bVector3 o3;
    int      i;

    printf("scenario point\n");

    // The constructor over a dirty point: the fields it never writes keep
    // the pattern, and that is the thing worth seeing.
    dirty(&p, sizeof p, 0x11);
    trpoint_init(&p);
    ppoint("ctor", &p);
    plines(&p);

    dirty(&p, sizeof p, 0xa3);
    trpoint_init(&p);
    ppoint("ctor2", &p);

    // A point with a real frame.
    memset(&p, 0, sizeof p);
    trpoint_init(&p);
    p.Position.x   = 10.0f;
    p.Position.y   = -4.0f;
    p.Elevation    = 2.5f;
    p.Direction.x  = 0.600000024f;
    p.Direction.y  = 0.800000012f;
    p.Length       = 21.0f;
    p.BankSlope    = 0.125f;
    p.ForwardSlope = -0.0625f;
    p.DistanceAroundTrack = 900.0f;

    for (i = -2; i <= 2; i++) {
        float d = (float)i * 13.0f;
        float l = (float)i * -3.5f;
        o3.pad = 12345.0f;
        trpoint_get_position2(&p, &o2, d, l);
        trpoint_get_position3(&p, &o3, d, l);
        printf("  at %.9g %.9g -> 2d %.9g %.9g 3d %.9g %.9g %.9g pad %.9g\n",
               d, l, o2.x, o2.y, o3.x, o3.y, o3.z, o3.pad);
    }

    // SetWidth's clamps, both ends and both arguments.
    {
        static const float w[] = { -5.0f, 0.5f, 1.0f, 7.25f, 64.0f, 100.0f };
        size_t a, b;
        for (a = 0; a < sizeof w / sizeof *w; a++)
            for (b = 0; b < sizeof w / sizeof *w; b++) {
                trpoint_set_width(&p, w[a], w[b]);
                printf("  width %.9g %.9g -> %.9g %.9g\n", w[a], w[b],
                       p.LeftWidth, p.RightWidth);
            }
    }

    // The driving-line scales: Q8 for the offset, whole units for the speed.
    for (i = 0; i < TRP_NUM_DRIVING_LINES; i++) {
        p.DrivingLineOffsets[i] = (int16_t)((i - 10) * 271);
        p.DrivingLineSpeeds[i]  = (uint8_t)(i * 12 + 3);
    }
    for (i = 0; i < TRP_NUM_DRIVING_LINES; i++)
        printf("  line %2d off %.9g spd %.9g\n", i,
               trpoint_get_driving_line_offset(&p, i),
               trpoint_get_driving_line_speed(&p, i));

    // The flag word, one field at a time.
    p.Bits = 0;
    p.Bits |= 0x2a;
    p.Bits |= 17u << TRP_ROADBLOCK_SHIFT;
    p.Bits |= 9u << TRP_TERRAIN_SHIFT;
    p.Bits |= 41u << TRP_RADARTRAP_SHIFT;
    p.Bits |= TRP_POSTED | TRP_POSTED_BACKWARDS;
    ppoint("bits", &p);
    p.Bits = 0xffffffffu;
    ppoint("allbits", &p);
}

static void scenario_build(void)
{
    TrackRoute *r = &gRoutes[0];
    int         i;

    printf("scenario build\n");
    rseed(0x13572468u);
    dirty(r, sizeof *r, 0x5c);
    build_route(r, 3, 9, -100.0f, 40.0f, 0.75f);
    proute("built", r);

    // GetRelativePoint at both ends and in the middle.
    for (i = 0; i < r->NumPoints; i++) {
        TrackRoutePoint *p = &r->TrackRoutePointTable[i];
        TrackRoutePoint *f = troute_get_relative_point(r, p, 1);
        TrackRoutePoint *b = troute_get_relative_point(r, p, 0);
        printf("  rel %d fwd %d back %d\n", i,
               f ? troute_get_point_number(r, f) : -1,
               b ? troute_get_point_number(r, b) : -1);
    }

    // CalculatePointDirection's return code: 1 when the gap is outside
    // [4, 24]. The built route's gaps straddle that.
    // The call writes Length, which the same printf reads, so it cannot
    // share an argument list with it.
    for (i = 0; i < r->NumPoints; i++) {
        int rc = troute_calculate_point_direction(
                     r, &r->TrackRoutePointTable[i]);
        printf("  calc %d -> %d len %.9g\n", i, rc,
               r->TrackRoutePointTable[i].Length);
    }

    // MovePoint, including the elevation-from-x quirk and the out-of-range
    // returns.
    for (i = 0; i < 4; i++) {
        bVector3 v;
        int      idx = i * 3;
        v.x = frand(50.0f);
        v.y = frand(50.0f);
        v.z = frand(10.0f);
        v.pad = 0.0f;
        if (idx >= r->NumPoints) idx = r->NumPoints - 1;
        printf("  move %d to %.9g %.9g %.9g -> %d\n", idx, v.x, v.y, v.z,
               troute_move_point(r, &r->TrackRoutePointTable[idx], &v));
        ppoint("moved", &r->TrackRoutePointTable[idx]);
    }
    // Past the end: the table slot exists, the point number does not.
    {
        bVector3 v;
        v.x = 1.0f; v.y = 2.0f; v.z = 3.0f; v.pad = 0.0f;
        printf("  move oob -> %d\n",
               troute_move_point(
                   r, &r->TrackRoutePointTable[r->NumPoints + 2], &v));
    }

    // AddPoint until it refuses. MaxPoints is knocked down so the test does
    // not have to fill 1024 slots to reach the edge.
    r->MaxPoints = r->NumPoints + 2;
    for (i = 0; i < 4; i++) {
        bVector2 p;
        p.x = frand(30.0f);
        p.y = frand(30.0f);
        printf("  add -> %s\n",
               troute_add_point(r, &p, 1.0f, 3.0f, 4.0f) ? "point" : "null");
    }
    printf("  pts %d max %d\n", r->NumPoints, r->MaxPoints);

    // One point, which is the only way to see the direction AddPoint seeds:
    // on any longer route the second AddPoint recomputes point zero.
    {
        TrackRoute *s = &gRoutes[4];
        bVector2    q;
        int         rc;
        dirty(s, sizeof *s, 0x1d);
        troute_init(s, 12);
        q.x = 3.0f;
        q.y = -7.0f;
        troute_add_point(s, &q, 2.0f, 5.0f, 6.0f);
        ppoint("lone", &s->TrackRoutePointTable[0]);
        rc = troute_calculate_point_direction(s,
                                              &s->TrackRoutePointTable[0]);
        printf("  lone calc %d\n", rc);
    }
}

static void scenario_driving_lines(void)
{
    TrackRoute *r = &gRoutes[1];
    int         i, j;

    printf("scenario driving lines\n");
    rseed(0x2468ace0u);
    dirty(r, sizeof *r, 0x77);
    build_route(r, 5, 6, 0.0f, 0.0f, -0.25f);

    for (i = 0; i < r->NumPoints; i++)
        for (j = 0; j < TRP_NUM_DRIVING_LINES; j++) {
            r->TrackRoutePointTable[i].DrivingLineOffsets[j] =
                (int16_t)((i * 31 + j * 7) - 200);
            r->TrackRoutePointTable[i].DrivingLineSpeeds[j] =
                (uint8_t)(i * 5 + j * 3);
        }
    for (i = 0; i < TRP_NUM_DRIVING_LINES; i++) {
        r->DrivingLineInfoTable[i].Flags = DLI_IS_VALID |
                                           (i & 1 ? DLI_IS_FAKE : 0);
        r->DrivingLineInfoTable[i].LineTime = 60.0f + (float)i;
        sprintf(r->DrivingLineInfoTable[i].DriverName, "DRIVER%d", i);
    }

    printf("  has %d\n", troute_has_driving_line_data(r));
    // Halfway point, line 0 and line 1, is the whole test.
    r->TrackRoutePointTable[r->NumPoints / 2].DrivingLineSpeeds[0] = 31;
    printf("  has31 %d\n", troute_has_driving_line_data(r));
    r->TrackRoutePointTable[r->NumPoints / 2].DrivingLineSpeeds[0] = 30;
    printf("  has30 %d\n", troute_has_driving_line_data(r));
    r->TrackRoutePointTable[r->NumPoints / 2].DrivingLineSpeeds[1] = 200;
    printf("  has200 %d\n", troute_has_driving_line_data(r));

    troute_erase_driving_line(r, 4);
    printf("  erased 4\n");
    for (i = 0; i < r->NumPoints; i++) plines(&r->TrackRoutePointTable[i]);
    for (i = 0; i < TRP_NUM_DRIVING_LINES; i++)
        printf("  line %2d flags %08lx time %.9g name %.20s\n", i,
               (unsigned long)r->DrivingLineInfoTable[i].Flags,
               r->DrivingLineInfoTable[i].LineTime,
               r->DrivingLineInfoTable[i].DriverName);
}

static void scenario_reverse(void)
{
    TrackRoute *r = &gRoutes[2];
    int         i;

    printf("scenario reverse\n");
    TheTrackPathManager.TrackLength = 4000.0f;
    rseed(0x0badf00du);
    dirty(r, sizeof *r, 0x2b);
    build_route(r, 7, 7, 200.0f, -50.0f, 0.5f);
    for (i = 0; i < r->NumPoints; i++) {
        int j;
        r->TrackRoutePointTable[i].DistanceAroundTrack = (float)i * 133.0f;
        r->TrackRoutePointTable[i].BankSlope = frand(0.5f);
        for (j = 0; j < TRP_NUM_DRIVING_LINES; j++) {
            r->TrackRoutePointTable[i].DrivingLineOffsets[j] =
                (int16_t)(i * 100 + j);
            r->TrackRoutePointTable[i].DrivingLineSpeeds[j] =
                (uint8_t)(i * 10 + j);
        }
    }
    for (i = 0; i < TRP_NUM_DRIVING_LINES; i++) {
        r->DrivingLineInfoTable[i].Flags    = (uint32_t)(i + 1);
        r->DrivingLineInfoTable[i].LineTime = (float)i * 2.5f;
        sprintf(r->DrivingLineInfoTable[i].DriverName, "L%d", i);
    }
    proute("before", r);

    trpoint_reverse_point(&r->TrackRoutePointTable[1]);
    printf("  one point reversed\n");
    ppoint("p1", &r->TrackRoutePointTable[1]);
    plines(&r->TrackRoutePointTable[1]);

    troute_reverse_route(r);
    proute("reversed", r);
    troute_reverse_route(r);
    proute("unreversed", r);

    // SwapPointData moves 48 bytes and no more, so the driving lines stay.
    trpoint_swap_point_data(&r->TrackRoutePointTable[0],
                            &r->TrackRoutePointTable[3]);
    printf("  swapped 0 and 3\n");
    ppoint("p0", &r->TrackRoutePointTable[0]);
    plines(&r->TrackRoutePointTable[0]);
    ppoint("p3", &r->TrackRoutePointTable[3]);
    plines(&r->TrackRoutePointTable[3]);

    troute_reverse_traffic_route(r);
    printf("  traffic reversed\n");
    for (i = 0; i < r->NumPoints; i++)
        printf("  dist %d %.9g\n", i,
               r->TrackRoutePointTable[i].DistanceAroundTrack);
}

static void scenario_find(void)
{
    TrackRoute *r = &gRoutes[3];
    int         i, f;

    printf("scenario find\n");
    TheTrackPathManager.TrackLength = 3000.0f;
    rseed(0xfeedbeefu);
    dirty(r, sizeof *r, 0x40);
    build_route(r, 9, 24, -50.0f, -50.0f, 0.3f);
    for (i = 0; i < r->NumPoints; i++) {
        TrackRoutePoint *p = &r->TrackRoutePointTable[i];
        p->DistanceAroundTrack = (float)i * 61.0f;
        p->Bits &= ~(TRP_POSTED | TRP_NO_HELISHEET);
        if (i % 3 == 0) p->Bits |= TRP_POSTED;
        if (i % 4 == 0) p->Bits |= TRP_NO_HELISHEET;
    }

    for (f = 0; f < 8; f++) {
        int flags = ((f & 1) ? TRFIND_AHEAD_ONLY : 0) |
                    ((f & 2) ? TRFIND_POSTED_ONLY : 0) |
                    ((f & 4) ? TRFIND_NO_HELISHEET : 0);
        int k;
        for (k = 0; k < 6; k++) {
            bVector2 q;
            float    radius = 20.0f + (float)k * 40.0f;
            TrackRoutePoint *p;
            q.x = frand(400.0f);
            q.y = frand(400.0f);
            p = troute_find_closest_point(r, &q, radius, flags, 0.0f);
            printf("  find flags %d r %.9g at %.9g %.9g -> %d\n", flags,
                   radius, q.x, q.y, p ? troute_get_point_number(r, p) : -1);
        }
    }

    // And the track-distance metric, which needs a TrackLength.
    for (i = 0; i < 6; i++) {
        bVector2 q;
        TrackRoutePoint *p;
        float d = (float)i * 250.0f;
        q.x = frand(400.0f);
        q.y = frand(400.0f);
        p = troute_find_closest_point(r, &q, 400.0f,
                                      TRFIND_BY_TRACK_DISTANCE, d);
        printf("  findd d %.9g at %.9g %.9g -> %d\n", d, q.x, q.y,
               p ? troute_get_point_number(r, p) : -1);
        printf("  away %.9g\n",
               trpoint_get_distance_away(&r->TrackRoutePointTable[3], &q, d));
    }

    // Outside the bounding box: the early-out.
    {
        bVector2 q;
        q.x = 100000.0f;
        q.y = 100000.0f;
        printf("  far -> %d\n",
               troute_find_closest_point(r, &q, 10.0f, 0, 0.0f) ? 1 : 0);
    }

    // FindClosestPointAhead from every start.
    for (i = 0; i < r->NumPoints; i++) {
        bVector2 q;
        TrackRoutePoint *p;
        q.x = r->TrackRoutePointTable[r->NumPoints / 2].Position.x;
        q.y = r->TrackRoutePointTable[r->NumPoints / 2].Position.y;
        p = troute_find_closest_point_ahead(r, &q,
                                            &r->TrackRoutePointTable[i]);
        printf("  ahead from %d -> %d\n", i,
               p ? troute_get_point_number(r, p) : -1);
    }
    printf("  ahead null %d %d\n",
           troute_find_closest_point_ahead(r, 0,
                                           &r->TrackRoutePointTable[0]) ? 1 : 0,
           troute_find_closest_point_ahead(r, &r->BBoxMin, 0) ? 1 : 0);
}

static void scenario_span(void)
{
    TrackRoute *r = &gRoutes[3];
    int         i;

    printf("scenario span\n");
    TheTrackPathManager.TrackLength = 900.0f;
    gTrackPathDistanceFn = test_distance;

    troute_set_first_and_last(r);
    printf("  span %.9g %.9g\n", r->fStartDistance, r->fEndDistance);
    for (i = 0; i < 12; i++) {
        float d = (float)i * 80.0f;
        printf("  within %.9g -> %d\n", d,
               troute_distance_is_within_route(r, d));
    }

    // A route that does not wrap: one bucket, and start below end.
    {
        TrackRoute *s = &gRoutes[4];
        rseed(0x600dbeefu);
        dirty(s, sizeof *s, 0x91);
        build_route(s, 11, 5, 0.0f, 0.0f, 0.0f);
        troute_set_first_and_last(s);
        printf("  nowrap span %.9g %.9g\n", s->fStartDistance,
               s->fEndDistance);
        for (i = 0; i < 12; i++) {
            float d = (float)i * 80.0f;
            printf("  nowrap within %.9g -> %d\n", d,
                   troute_distance_is_within_route(s, d));
        }
    }

    // Steps a third of a lap long: a jump under a quarter-lap threshold
    // and not under a half-lap one, which is the only thing that tells the
    // two apart. Every other route here steps about eleven units.
    {
        TrackRoute *w = &gRoutes[4];
        int         k;
        dirty(w, sizeof *w, 0x3e);
        troute_init(w, 13);
        for (k = 0; k < 3; k++) {
            bVector2 q;
            q.x = (float)k * 600.0f;
            q.y = 0.0f;
            troute_add_point(w, &q, 0.0f, 5.0f, 5.0f);
        }
        troute_set_first_and_last(w);
        printf("  wide span %.9g %.9g\n", w->fStartDistance,
               w->fEndDistance);
    }

    // CompareDistances itself, which is the one piece of trackpath the
    // object depends on.
    for (i = -6; i <= 6; i++) {
        float a = 450.0f + (float)i * 100.0f;
        printf("  cmp %.9g -> %.9g\n", a,
               trackpath_compare_distances(&TheTrackPathManager, a, 450.0f));
    }

    gTrackPathDistanceFn = 0;
}

// ------------------------------------------------------------ chunk loading

// Writes `r`'s truncated memory image at `out` and returns its length, the
// way the bundle holds it.
static size_t emit_route(uint8_t *out, TrackRoute *r)
{
    size_t n = (size_t)sizeof(TrackRoute) -
               (size_t)(TRACK_ROUTE_MAX_POINTS - r->NumPoints) *
                   sizeof(TrackRoutePoint);
    memcpy(out, r, n);
    ((TrackRoute *)(void *)out)->Flags |= TROUTE_MEMORY_IMAGE_LOADED;
    return n;
}

static void scenario_load(void)
{
    uint8_t *p = gChunk + 8;
    size_t   used;
    int      i;

    printf("scenario load\n");
    rseed(0x0c0ffeeu);
    for (i = 0; i < 4; i++) {
        static const int nums[4] = { 2, 4, 50, 61 };
        dirty(&gRoutes[i], sizeof gRoutes[i], (uint8_t)(0x30 + i));
        build_route(&gRoutes[i], nums[i], 3 + i * 2, (float)i * 100.0f,
                    (float)i * -30.0f, 0.2f);
        p += emit_route(p, &gRoutes[i]);
    }
    used = (size_t)(p - (gChunk + 8));
    bchunk_put_u32(gChunk, CHUNK_TRACK_ROUTES);
    bchunk_put_u32(gChunk + 4, (uint32_t)used);
    printf("  payload %lu bytes\n", (unsigned long)used);

    trmgr_init(&TheTrackRouteManager);
    plists(&TheTrackRouteManager);
    printf("  loader -> %d\n", track_routes_loader(gChunk));
    plists(&TheTrackRouteManager);
    for (i = 0; i < TRACK_ROUTE_MAX_ROUTES; i++)
        if (TheTrackRouteManager.pTrackRoutes[i])
            printf("  slot %d n %d pts %d flags %08lx\n", i,
                   (int)TheTrackRouteManager.pTrackRoutes[i]->RouteNumber,
                   TheTrackRouteManager.pTrackRoutes[i]->NumPoints,
                   (unsigned long)TheTrackRouteManager.pTrackRoutes[i]->Flags);

    // The manager's FindClosestPoint, and what the two skip flags do to it.
    for (i = 0; i < 4; i++) {
        static const int fl[4] = { 0, TRFIND_SKIP_RACING, TRFIND_SKIP_TRAFFIC,
                                   TRFIND_SKIP_RACING | TRFIND_SKIP_TRAFFIC };
        int k;
        for (k = 0; k < 4; k++) {
            bVector2 q;
            TrackRoutePoint *pt;
            q.x = frand(400.0f);
            q.y = frand(400.0f);
            pt = trmgr_find_closest_point(&TheTrackRouteManager, &q, 500.0f,
                                          fl[i], 0.0f);
            printf("  mfind flags %d at %.9g %.9g -> %s %d\n", fl[i], q.x,
                   q.y, pt ? "rnum" : "null",
                   pt ? (int)pt->RouteNumber : -1);
        }
    }

    // Unload: memory images are unlinked but never freed.
    printf("  unloader -> %d\n", track_routes_unloader(gChunk));
    plists(&TheTrackRouteManager);
    for (i = 0; i < TRACK_ROUTE_MAX_ROUTES; i++)
        if (TheTrackRouteManager.pTrackRoutes[i])
            printf("  leftover %d\n", i);

    // A chunk that is not ours.
    bchunk_put_u32(gChunk, 0x00034999u);
    printf("  foreign load %d unload %d\n", track_routes_loader(gChunk),
           track_routes_unloader(gChunk));
    bchunk_put_u32(gChunk, CHUNK_TRACK_ROUTES);

    // The signpost chunk. There is no count field anywhere in it: the
    // loader divides the size by retail's twelve and that is the count.
    // Eight bytes over three signs, so a shift would not do.
    {
        uint32_t sc32[(8 + 3 * 12 + 8) / 4];
        uint8_t *sc = (uint8_t *)sc32;
        int      k, rc;
        bchunk_put_u32(sc, CHUNK_TRACK_SIGNPOSTS);
        bchunk_put_u32(sc + 4, 3 * 12 + 8);
        for (k = 0; k < 3 * 12 + 8; k++) sc[8 + k] = (uint8_t)(k * 11 + 1);
        rc = track_routes_loader(sc);
        printf("  sign chunk load %d n %lu present %d\n", rc,
               (unsigned long)NumSignposts, signposts_present());
        psigns("from chunk");
        rc = track_routes_unloader(sc);
        printf("  sign chunk unload %d n %lu present %d\n", rc,
               (unsigned long)NumSignposts, signposts_present());
    }
}

// ----------------------------------------------------------- sort and signs

static float cmp_float_entry(const void *a, const void *b)
{
    return *(const float *)a - *(const float *)b;
}

// Two equal floats are the same transcript line whichever order they land
// in, so a tie in a float array cannot show which way the sort broke it.
// A tag can.
typedef struct TaggedFloat {
    float Value;
    int   Tag;
} TaggedFloat;

static float cmp_tagged(const void *a, const void *b)
{
    return ((const TaggedFloat *)a)->Value - ((const TaggedFloat *)b)->Value;
}

static void scenario_sort(void)
{
    static const int sizes[] = { 0, 1, 2, 3, 7, 16, 17 };
    size_t s;

    printf("scenario sort\n");
    rseed(0xa5a5f00fu);
    for (s = 0; s < sizeof sizes / sizeof *sizes; s++) {
        float v[24];
        int   n = sizes[s];
        int   i;
        for (i = 0; i < n; i++) v[i] = frand(100.0f);
        printf("  in %d:", n);
        for (i = 0; i < n; i++) printf(" %.9g", v[i]);
        printf("\n");
        heap_sort(v, n, (int)sizeof v[0], cmp_float_entry);
        printf("  out %d:", n);
        for (i = 0; i < n; i++) printf(" %.9g", v[i]);
        printf("\n");
    }
    // Ties, which a heapsort is free to reorder -- worth pinning down.
    {
        float v[6] = { 2.0f, 1.0f, 2.0f, 1.0f, 2.0f, 1.0f };
        int   i;
        heap_sort(v, 6, (int)sizeof v[0], cmp_float_entry);
        printf("  ties:");
        for (i = 0; i < 6; i++) printf(" %.9g", v[i]);
        printf("\n");
    }
    {
        static const float vals[9] = { 3.0f, 1.0f, 2.0f, 1.0f, 3.0f, 2.0f,
                                       1.0f, 3.0f, 2.0f };
        TaggedFloat t[9];
        int         i;
        for (i = 0; i < 9; i++) {
            t[i].Value = vals[i];
            t[i].Tag   = i;
        }
        heap_sort(t, 9, (int)sizeof t[0], cmp_tagged);
        printf("  tagged:");
        for (i = 0; i < 9; i++) printf(" %.9g/%d", t[i].Value, t[i].Tag);
        printf("\n");
    }
}

static void scenario_signs(void)
{
    int i;

    printf("scenario signs\n");
    TheTrackPathManager.TrackLength = 900.0f;
    gTrackPathDistanceFn = test_distance;

    // Rebuild the four routes and load them, so the signs have somewhere to
    // point.
    rseed(0x77777777u);
    {
        uint8_t *p = gChunk + 8;
        size_t   used;
        static const int nums[4] = { 1, 2, 50, 51 };
        for (i = 0; i < 4; i++) {
            dirty(&gRoutes[i], sizeof gRoutes[i], (uint8_t)(0x50 + i));
            build_route(&gRoutes[i], nums[i], 6 + i, (float)i * 90.0f,
                        (float)i * 45.0f, 0.4f);
            p += emit_route(p, &gRoutes[i]);
        }
        used = (size_t)(p - (gChunk + 8));
        bchunk_put_u32(gChunk, CHUNK_TRACK_ROUTES);
        bchunk_put_u32(gChunk + 4, (uint32_t)used);
        trmgr_init(&TheTrackRouteManager);
        track_routes_loader(gChunk);
    }

    // Eight signs in pairs, the way the disc lays them out: sign i's target
    // point names sign i^1.
    printf("  signposts present %d\n", signposts_present());
    SignpostArray = gSigns;
    NumSignposts  = 8;
    for (i = 0; i < 8; i++) {
        static const uint8_t route[8] = { 1, 2, 2, 1, 1, 50, 50, 51 };
        static const int32_t hint[8]  = { 0, 1, 2, 0, 2, 1, -1, 7 };
        gSigns[i].NewRoute = route[i];
        gSigns[i].NewPoint = (uint16_t)(1 + i / 2);
        gSigns[i].Flags    = (uint8_t)((i & 7) | ((i & 1) << 3));
        gSigns[i].Distance = 0.0f;
        gSigns[i].AIHint   = hint[i];
    }
    for (i = 0; i < 8; i++) {
        TrackRoutePoint *p = signpost_get_new_route_point(&gSigns[i]);
        if (!p) continue;
        p->Bits = (p->Bits & ~TRP_SIGN_MASK) | (uint32_t)(i ^ 1);
    }
    printf("  signposts present %d\n", signposts_present());
    psigns("initial");

    for (i = 0; i < 8; i++) {
        TrackRoute      *r = signpost_get_new_route(&gSigns[i]);
        TrackRoutePoint *p = signpost_get_new_route_point(&gSigns[i]);
        printf("  sign %d route %d point %d racing %d\n", i,
               r ? (int)r->RouteNumber : -1,
               p ? troute_get_point_number(r, p) : -1,
               signpost_is_racing_route(&gSigns[i]));
    }

    signpost_set_distances();
    psigns("distances");

    for (i = -1; i < 12; i++) {
        float d = (float)i * 90.0f;
        printf("  index %.9g -> %d\n", d, signpost_get_index(d));
    }

    signpost_reverse_signs();
    psigns("reversed");
    signpost_reverse_signs();
    psigns("unreversed");

    signpost_test_consistency();
    printf("  consistency ran\n");

    gTrackPathDistanceFn = 0;
}

static void scenario_init(void)
{
    int i;

    printf("scenario init\n");
    TheTrackPathManager.TrackLength = 900.0f;
    gTrackPathDistanceFn = test_distance;

    // Shuffle the distances so the sort has work to do, then run the whole
    // end-of-load sequence forwards.
    for (i = 0; i < 8; i++) gSigns[i].Distance = 0.0f;
    init_track_routes(1);
    psigns("after init fwd");
    for (i = 0; i < TRACK_ROUTE_MAX_ROUTES; i++) {
        TrackRoute *r = TheTrackRouteManager.pTrackRoutes[i];
        int         j;
        if (!r) continue;
        printf("  route %d flags %08lx span %.9g %.9g\n", (int)r->RouteNumber,
               (unsigned long)r->Flags, r->fStartDistance, r->fEndDistance);
        for (j = 0; j < r->NumPoints; j++)
            printf("    p%d sign %lu\n", j,
                   (unsigned long)trpoint_sign_number(
                       &r->TrackRoutePointTable[j]));
    }

    // And backwards, which reverses every route and every sign first.
    init_track_routes(0);
    psigns("after init rev");
    for (i = 0; i < TRACK_ROUTE_MAX_ROUTES; i++) {
        TrackRoute *r = TheTrackRouteManager.pTrackRoutes[i];
        if (!r) continue;
        printf("  route %d flags %08lx span %.9g %.9g\n", (int)r->RouteNumber,
               (unsigned long)r->Flags, r->fStartDistance, r->fEndDistance);
    }

    close_track_routes();
    printf("  closed\n");
    gTrackPathDistanceFn = 0;
}

// ------------------------------------------------------------ retail's disc

static void proute_summary(const TrackRoute *r)
{
    int j;

    printf("  route %d type %d pts %d flags %08lx span %.9g %.9g\n",
           (int)r->RouteNumber, (int)r->Type, r->NumPoints,
           (unsigned long)r->Flags, r->fStartDistance, r->fEndDistance);
    printf("    signed");
    for (j = 0; j < r->NumPoints; j++) {
        uint32_t s = trpoint_sign_number(&r->TrackRoutePointTable[j]);
        if (s != TRP_SIGN_MASK) printf(" %d/%lu", j, (unsigned long)s);
    }
    printf("\n");
}

static void proutes(void)
{
    int i;
    for (i = 0; i < TRACK_ROUTE_MAX_ROUTES; i++)
        if (TheTrackRouteManager.pTrackRoutes[i])
            proute_summary(TheTrackRouteManager.pTrackRoutes[i]);
}

// A retail track's own routes and signs, in place in the bundle as the game
// has them: the 12-byte stride, the divide and the DontTake pass on data
// nobody built for the test.
static int scenario_disc(const char *path)
{
    const char    *name = strrchr(path, '/');
    const char    *bs   = strrchr(path, '\\');
    FILE          *fh;
    long           len;
    uint8_t       *data;
    const uint8_t *rp, *sp;
    uint8_t       *ro, *so;
    uint32_t       rsize = 0, ssize = 0;
    char           stem[64];
    size_t         k;

    if (bs && (!name || bs > name)) name = bs;
    name = name ? name + 1 : path;
    for (k = 0; name[k] && name[k] != '.' && k + 1 < sizeof stem; k++)
        stem[k] = name[k];
    stem[k] = 0;

    fh = fopen(path, "rb");
    if (!fh) {
        perror(path);
        return 1;
    }
    fseek(fh, 0, SEEK_END);
    len = ftell(fh);
    fseek(fh, 0, SEEK_SET);
    data = (uint8_t *)malloc((size_t)len);
    if (!data || fread(data, 1, (size_t)len, fh) != (size_t)len) {
        fclose(fh);
        return 1;
    }
    fclose(fh);

    printf("scenario disc %s\n", stem);
    rp = bchunk_find_deep(data, 0, (size_t)len, CHUNK_TRACK_ROUTES, &rsize);
    sp = bchunk_find_deep(data, 0, (size_t)len, CHUNK_TRACK_SIGNPOSTS, &ssize);
    if (!rp || !sp) return 1;
    ro = data + (rp - data) - 8;
    so = data + (sp - data) - 8;
    printf("  routes %lu bytes signs %lu bytes\n", (unsigned long)rsize,
           (unsigned long)ssize);

    trmgr_init(&TheTrackRouteManager);
    {
        int a = track_routes_loader(ro);
        int b = track_routes_loader(so);
        printf("  load routes %d signs %d n %lu\n", a, b,
               (unsigned long)NumSignposts);
    }
    plists(&TheTrackRouteManager);
    proutes();
    psigns("loaded");

    TheTrackPathManager.TrackLength = 20000.0f;
    gTrackPathDistanceFn = test_distance;
    init_track_routes(1);
    psigns("fwd");
    proutes();
    init_track_routes(0);
    psigns("rev");
    proutes();
    gTrackPathDistanceFn = 0;

    {
        int a = track_routes_unloader(so);
        int b = track_routes_unloader(ro);
        printf("  unload signs %d routes %d n %lu present %d\n", a, b,
               (unsigned long)NumSignposts, signposts_present());
    }
    plists(&TheTrackRouteManager);
    free(data);
    return 0;
}

int main(int argc, char **argv)
{
    int a;

    // The manager is deliberately not in this list: it is the one structure
    // here that is never overlaid on chunk bytes, so it is allowed to be as
    // wide as the host's pointers.
    printf("sizes route %lu point %lu info %lu sign %lu\n",
           (unsigned long)sizeof(TrackRoute),
           (unsigned long)sizeof(TrackRoutePoint),
           (unsigned long)sizeof(DrivingLineInfo),
           (unsigned long)sizeof(Signpost));
    scenario_point();
    scenario_build();
    scenario_driving_lines();
    scenario_reverse();
    scenario_find();
    scenario_span();
    scenario_load();
    scenario_sort();
    scenario_signs();
    scenario_init();
    for (a = 1; a < argc; a++)
        if (scenario_disc(argv[a])) return 1;
    return 0;
}
