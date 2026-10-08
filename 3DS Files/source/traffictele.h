// traffictele -- TrafficTeleporter from retail: the World's placer of
// traffic cars. It puts each traffic car somewhere on a traffic route at
// the start, then, while the race runs, moves the ones out of sight to
// somewhere ahead of or behind a player, out of sight too, and repaints
// them, so the traffic seems endless.
//
// Retail's TrafficTeleporter.obj is 0x002226f8 .. 0x002232c0 (the demo's
// 0x0020e610 .. 0x0020f0f0). The layout is the demo's .mdebug type#1882,
// 88 bytes, and retail's constructor stores the same fields.
//
// What is here, all of it but DoSnapshot:
//   0x002226f8  the constructor: both totals, SetThinkTime, the first
//               think held to 20 s, and the first car
//   0x00222760  the destructor: nothing but the delete, on flags & 1
//   0x002227e0  DoTimestep: every think, one traffic car out of sight moved
//   0x002228e0  PlaceNewCar: a new traffic car somewhere good
//   0x00222a90  TryToTeleportCar: one car moved ahead of a player
//   0x00222c40  IsGoodPlace (retail's own; the name is the port's)
//   0x00222d88  CheckIsVisible(bVector2 *), which nothing calls
//   0x00222dc8  CheckIsVisible(float)
//   0x00222e10  SetThinkTime: (1 - TrafficDensity) * 15 + 1
//   0x00222e40  ForwardsOrBackwards
//   0x00222e88  FillInTotals: running point counts over ten routes
//   0x00222ee8  TooCloseToAnotherCar(bVector2 *, ...), which nothing calls
//   0x00222fc0  TooCloseToAnotherCar(float, ...)
//   0x002230d0  PickRoutePoint (retail's own; the name is the port's)
//   0x002231f0  RandomPlayerCar
//   0x00223228  PickRandomSkin
//   0x00223278  SwitchSkin
//
// DoSnapshot (0x00222780: TimeUntilTeleport and LastCar into the
// "TrafficTeleporter" section) waits on ReplaySnapshot, as every
// DoSnapshot does.
//
// Written up in docs/formats/traffic-teleporter.md.

#ifndef TRAFFICTELE_H
#define TRAFFICTELE_H

#include <stddef.h>
#include <stdint.h>

#include "airoute.h"
#include "bvector.h"

struct Car;
struct CarTypeInfo;
struct DriverInfo;

// The traffic routes: 50 to 59 one way, 60 to 69 the other
// (trmgr_reverse_routes' "50..69 as traffic").
#define TRAFFIC_FORWARD_ROUTES  50
#define TRAFFIC_BACKWARD_ROUTES 60
#define TRAFFIC_ROUTES_EACH     10

// LastCar is a Car * in the demo's .mdebug, but retail keeps an index in
// it: the traffic car DoTimestep looked at last, counted from the
// World's TrafficCarPos.
typedef struct TrafficTeleporter {
    float       TimeUntilTeleport;                     //  0
    int32_t     LastCar;                               //  4
    uint32_t    ForwardTotals[TRAFFIC_ROUTES_EACH];    //  8
    uint32_t    BackwardTotals[TRAFFIC_ROUTES_EACH];   // 48
} TrafficTeleporter;                                   // 88

typedef char traffictele_layout_check[
    (offsetof(TrafficTeleporter, LastCar) == 4
     && offsetof(TrafficTeleporter, ForwardTotals) == 8
     && offsetof(TrafficTeleporter, BackwardTotals) == 48
     && sizeof(TrafficTeleporter) == 88) ? 1 : -1];

// Retail's literals.
#define TELEPORT_MIN_DENSITY  0.4f      // gp-27148: thinner, none move
#define TELEPORT_SIGHT        250.0f    // visible inside this of a player
#define TELEPORT_FIRST_AHEAD  250.0f    // the first place tried, on
#define TELEPORT_STEP_AHEAD   50.0f     // and each after
#define TELEPORT_SPEED        24.5865f  // gp-27144: a moved car's speed
#define TELEPORT_TOO_CLOSE    100.0f
#define TELEPORT_START_TIME   20.0f     // s the start line is kept clear
#define TELEPORT_START_CLEAR  2000.0f   // and how far round it
#define TELEPORT_PLACE_TRIES  100
#define TELEPORT_PICK_TRIES   101

// 0x002226f8, on the 88 bytes World has bMalloc'd. world.h's
// gTrafficTeleporterCtorFn takes it.
TrafficTeleporter *traffic_teleporter_construct(void *mem);

// 0x00222760: ~TrafficTeleporter has nothing to undo, and bFree's the
// block on flags & 1. world.h's gTrafficTeleporterDestroyFn takes it.
void traffic_teleporter_destroy(TrafficTeleporter *t, int32_t flags);

// 0x002227e0, world.h's gTrafficTeleporterDoTimestepFn. Nothing below 0.4
// density, with no traffic, outside RACE_STAGE_RACING or with no players.
// Otherwise the clock runs down by `dt`; when it reaches 0 it is set again
// and the traffic cars after LastCar are looked at in turn, round to
// LastCar again. The first not visible is tried with TryToTeleportCar and
// becomes LastCar.
void traffic_teleporter_do_timestep(TrafficTeleporter *t, float dt);

// 0x002228e0, world.h's gTrafficTeleporterPlaceNewCarFn: a traffic car for
// `info`, at a random point of the traffic routes that IsGoodPlace likes,
// with up to 100 tries. It faces the point's way, with a random skin
// (written into `info`), on traffic control, not moving and not drawn;
// racerun.c starts it at the countdown. NULL when either way has no
// points, or no try was good.
struct Car *traffic_teleporter_place_new_car(TrafficTeleporter *t,
                                             struct DriverInfo *info);

// 0x00222a90. Moves `c` to the first good place 250 on from where a random
// player is on the traffic routes, and then each 50 on, in a random
// direction. It gives up off the routes, behind the player, and past the
// car when the car was already ahead. A moved car is on traffic movement
// at 24.5865 with a new random skin.
void traffic_teleporter_try_to_teleport_car(TrafficTeleporter *t,
                                            struct Car *c);

// 0x00222c40. Not within 2000 of the start line while the race is under
// 20 s old, not visible, and not too close to a car but `except`
// (TooCloseToAnotherCar with `all`).
int32_t traffic_teleporter_is_good_place(TrafficTeleporter *t,
                                         const NearestRoutePointInfo *info,
                                         struct Car *except, int32_t all);

// 0x00222dc8. Within 250 round the track of the nearest player.
int32_t traffic_teleporter_check_is_visible(TrafficTeleporter *t, float dat);

// 0x00222d88. Within 250 of the nearest player in the plane.
int32_t traffic_teleporter_check_is_visible_at(TrafficTeleporter *t,
                                               const bVector2 *pos);

// 0x00222e10. TimeUntilTeleport from TheRaceParameters.TrafficDensity:
// 16 s with none, 1 s at full.
void traffic_teleporter_set_think_time(TrafficTeleporter *t);

// 0x00222e40. 1 for the forward routes, with TrafficOncoming's chance of
// 0 for the oncoming ones.
int32_t traffic_teleporter_forwards_or_backwards(TrafficTeleporter *t);

// 0x00222e88. out[i] is the sum of NumPoints over routes first .. first+i,
// a missing route counting 0 -- so a route's share of the totals is its
// length, which is how PlaceNewCar picks one.
void traffic_teleporter_fill_in_totals(TrafficTeleporter *t, uint32_t *out,
                                       int32_t first);

// 0x00222fc0. Over the World's cars but `except`, the poofed and, without
// `all`, the undrawn: a traffic car within 100 either way round the track
// of `dat`, or any other car up to 100 behind it.
int32_t traffic_teleporter_too_close_to_another_car(TrafficTeleporter *t,
                                                    float dat,
                                                    struct Car *except,
                                                    int32_t all);

// 0x00222ee8. The same cars, within 100 of `pos` in the plane.
int32_t traffic_teleporter_too_close_at(TrafficTeleporter *t,
                                        const bVector2 *pos,
                                        struct Car *except, int32_t all);

// 0x002230d0. A random point of the forward or the backward traffic
// routes, each point as likely; tried again, up to 101 times in all,
// while it is not Posted.
void traffic_teleporter_pick_route_point(TrafficTeleporter *t,
                                         NearestRoutePointInfo *out,
                                         int32_t fwd);

// 0x002231f0. A random player's car.
struct Car *traffic_teleporter_random_player_car(TrafficTeleporter *t);

// 0x00223228. A random one of the type's skins, or 0 with none.
int32_t traffic_teleporter_pick_random_skin(TrafficTeleporter *t,
                                            const struct CarTypeInfo *ct);

// 0x00223278. A random skin for `c`, put on when it is not the one it has.
void traffic_teleporter_switch_skin(TrafficTeleporter *t, struct Car *c);

#endif
