// traffictele -- TrafficTeleporter from retail: the World's placer of
// traffic cars, its constructor and destructor so far.
//
// Retail's TrafficTeleporter.obj is 0x002226f8 .. 0x002232c0 (the demo's
// 0x0020e610 .. 0x0020f0f0). The layout is the demo's .mdebug type#1882,
// 88 bytes, and retail's constructor stores the same fields.
//
// What is here:
//   0x002226f8  the constructor: both totals, SetThinkTime, the first
//               think held to 20 s, and no last car
//   0x00222760  the destructor: nothing but the delete, on flags & 1
//   0x00222e10  SetThinkTime: (1 - TrafficDensity) * 15 + 1
//   0x00222e88  FillInTotals: running point counts over ten routes
//
// DoTimestep, PlaceNewCar, TryToTeleportCar and the rest wait on traffic:
// World's seams for them stay NULL, which DoTimestep skips and
// AddTrafficCar aborts on.

#ifndef TRAFFICTELE_H
#define TRAFFICTELE_H

#include <stddef.h>
#include <stdint.h>

struct Car;

// The traffic routes: 50 to 59 one way, 60 to 69 the other
// (trmgr_reverse_routes' "50..69 as traffic").
#define TRAFFIC_FORWARD_ROUTES  50
#define TRAFFIC_BACKWARD_ROUTES 60
#define TRAFFIC_ROUTES_EACH     10

typedef struct TrafficTeleporter {
    float       TimeUntilTeleport;                     //  0
    struct Car *LastCar;                               //  4
    uint32_t    ForwardTotals[TRAFFIC_ROUTES_EACH];    //  8
    uint32_t    BackwardTotals[TRAFFIC_ROUTES_EACH];   // 48
} TrafficTeleporter;                                   // 88

#if UINTPTR_MAX == 0xffffffffu
typedef char traffictele_layout_check[
    (offsetof(TrafficTeleporter, LastCar) == 4
     && offsetof(TrafficTeleporter, ForwardTotals) == 8
     && offsetof(TrafficTeleporter, BackwardTotals) == 48
     && sizeof(TrafficTeleporter) == 88) ? 1 : -1];
#endif

// 0x002226f8, on the 88 bytes World has bMalloc'd. world.h's
// gTrafficTeleporterCtorFn takes it.
TrafficTeleporter *traffic_teleporter_construct(void *mem);

// 0x00222760: ~TrafficTeleporter has nothing to undo, and bFree's the
// block on flags & 1. world.h's gTrafficTeleporterDestroyFn takes it.
void traffic_teleporter_destroy(TrafficTeleporter *t, int32_t flags);

// 0x00222e10. TimeUntilTeleport from TheRaceParameters.TrafficDensity:
// 16 s with none, 1 s at full.
void traffic_teleporter_set_think_time(TrafficTeleporter *t);

// 0x00222e88. out[i] is the sum of NumPoints over routes first .. first+i,
// a missing route counting 0 -- so a route's share of the totals is its
// length, which is how PlaceNewCar picks one.
void traffic_teleporter_fill_in_totals(TrafficTeleporter *t, uint32_t *out,
                                       int32_t first);

#endif
