// trackroute -- TrackRoute.obj (0x001b6f60 .. 0x001b9558), the whole object.
//
// A TrackRoute is a driving line, not geometry: a run of up to 1024 points,
// each one a 2D position with an elevation, a unit direction, a left and a
// right width and a bank. The track's collision and scenery are elsewhere;
// this is the thing a car, a cop or a camera asks "where is the road, which
// way does it go, and how far off it am I".
//
// Two kinds share the file, told apart by route number rather than by type:
// 1..49 are racing routes and 50..69 are traffic routes. The constructor
// derives Type from the number and TrackRouteManager keeps one list of each.
// Track 12 ships thirteen racing routes (1..13) and four traffic ones
// (50, 51, 60, 61).
//
// Three things are worth knowing before reading the code.
//
// **Routes load in place, truncated.** The 0x00034121 chunk is a run of
// TrackRoute *memory images* with the unused tail of the point table cut
// off, so the stride is `sizeof(TrackRoute) - (1024 - NumPoints) * 112`, not
// sizeof(TrackRoute). TrackRoutePointTable is declared [1024] here because
// that is the object's shape, but on a loaded route only the first NumPoints
// entries are the route's own memory -- entry NumPoints is the next route's
// header. The original has exactly the same property and nothing in it
// indexes past NumPoints. Neither does this.
//
// **The point's flag word is one uint32_t, not C bitfields.** The disc's
// layout is fixed and the port overlays it on chunk bytes; a compiler is
// free to lay bitfields out differently, so the masks are written down.
//
// **The Espresso half is not here.** `TrackRoute::UpdateToCaffeine`
// (0x001b7de8) is 260 instructions of espCreateObject / espSetAttributeFloat
// / espCreateUserMesh -- it uploads the route to *Caffeine*, the track
// editor, over the bFunk socket protocol that EspClient.obj speaks to a host
// named "EspressoServer". "Esp" is a live editor link, not a file format,
// and `espEmptyLayer` empties a layer in the running editor's database. Its
// only caller is TrackRouteEditor::Service. See docs/formats/track-route.md.
//
// Ported from the disassembly and checked by tools/trackroute_check.py.
#ifndef TRACKROUTE_H
#define TRACKROUTE_H

#include <stdint.h>

#include "bvector.h"

// --------------------------------------------------------------- signposts

// Sorted by distance around the track at init time, and referenced by index
// from every point that has one. 0xff in a point's SignNumber means none.
//
// Eight bytes, read on the disc as a byte, a halfword and a word over the
// same four bytes; spelled out here so the bit numbers are visible.
typedef struct Signpost {
    uint8_t  NewRoute;  // 0   the route this sign sends you down
    uint8_t  Flags;     // 1   bits 0-2 Sign, 3 Backwards, 4 NoStakeout,
                        //     5 Hairpin, 6 Cloaked
    uint16_t NewPoint;  // 2   index into that route's point table
    float    Distance;  // 4   distance around the track, filled by
                        //     signpost_set_distances
} Signpost;

#define SIGNPOST_SIGN_MASK    0x07u
#define SIGNPOST_BACKWARDS    0x08u
#define SIGNPOST_NO_STAKEOUT  0x10u
#define SIGNPOST_HAIRPIN      0x20u
#define SIGNPOST_CLOAKED      0x40u

// `SignpostArray` / `NumSignposts` at 0x003241d0 / 0x003241d4. The array is
// the 0x00034122 chunk's payload, in place.
extern Signpost *SignpostArray;
extern uint32_t  NumSignposts;

// ------------------------------------------------------------- route points

// 112 bytes.
typedef struct TrackRoutePoint {
    bVector2 Position;              // 0
    float    Elevation;             // 8
    bVector2 Direction;             // 12  unit, in the XY plane
    float    Length;                // 20  to the next point
    float    LeftWidth;             // 24
    float    RightWidth;            // 28
    float    BankSlope;             // 32  dz per unit of lateral offset
    float    ForwardSlope;          // 36  dz per unit along
    float    DistanceAroundTrack;   // 40
    uint32_t Bits;                  // 44  see below
    int16_t  DrivingLineOffsets[21];// 48  Q8 lateral offsets
    uint8_t  DrivingLineSpeeds[21]; // 90  whole units
    uint8_t  RouteNumber;           // 111
} TrackRoutePoint;

// The flag word at offset 44, LSB first, as the .mdebug bitfield offsets
// give it (352, 360, 366, 367, 368, 374, 380).
#define TRP_SIGN_SHIFT        0
#define TRP_SIGN_MASK         0x000000ffu  // 0xff = no signpost
#define TRP_ROADBLOCK_SHIFT   8
#define TRP_ROADBLOCK_MASK    0x00003f00u  // 0x3f = none
#define TRP_NO_HELISHEET      0x00004000u
#define TRP_POSTED            0x00008000u
#define TRP_TERRAIN_SHIFT     16
#define TRP_TERRAIN_MASK      0x003f0000u
#define TRP_RADARTRAP_SHIFT   22
#define TRP_RADARTRAP_MASK    0x0fc00000u  // 0x3f = none
#define TRP_POSTED_BACKWARDS  0x10000000u

#define TRP_NUM_DRIVING_LINES 21

// ------------------------------------------------------------------- routes

typedef enum TrackRouteType {
    TRACK_ROUTE_RACING  = 0,
    TRACK_ROUTE_TRAFFIC = 1,
} TrackRouteType;

// 48 bytes. One per driving line; only IsValid, IsFake and LineTime are read
// by anything, and DriverName is a saved ghost's name.
typedef struct DrivingLineInfo {
    uint32_t Flags;         // 0   bit0 IsValid, bit1 IsFake
    float    LineTime;      // 4
    char     DriverName[40];// 8
} DrivingLineInfo;

#define DLI_IS_VALID 0x01u
#define DLI_IS_FAKE  0x02u

#define TRACK_ROUTE_MAX_POINTS 1024

// 115752 bytes, with the caveat at the top of this file about the tail.
typedef struct TrackRoute {
    // bTNode<TrackRoute> on the disc: a circular doubly-linked list whose
    // head is the manager's own first bytes, so `Next` on the last route
    // points back into TrackRouteManager rather than at a route.
    //
    // They are two raw words here, and the port never dereferences them.
    // A loaded route *is* the chunk's bytes, so the record has to be 115752
    // bytes wide on every machine the checker or the handheld runs on, and
    // two pointers are not. The lists live in the manager instead; they keep
    // the same order and the same contents, which is all anything reads.
    // What the disc left in these eight bytes is a pair of PS2 addresses.
    uint32_t NodeNext;             // 0
    uint32_t NodePrev;             // 4
    int16_t  Version;              // 8   1 on the disc
    int16_t  RouteNumber;          // 10
    int32_t  Type;                 // 12  TrackRouteType
    int32_t  NumPoints;            // 16
    int32_t  MaxPoints;            // 20  == NumPoints on a loaded route
    uint32_t Flags;                // 24  bit0 MemoryImageLoaded, bit1 Reversed
    int32_t  CurrentlyTuningDrivingLine; // 28
    float    fStartDistance;       // 32  filled by SetFirstAndLast
    float    fEndDistance;         // 36
    DrivingLineInfo DrivingLineInfoTable[TRP_NUM_DRIVING_LINES]; // 40
    bVector2 BBoxMin;              // 1048
    bVector2 BBoxMax;              // 1056
    TrackRoutePoint TrackRoutePointTable[TRACK_ROUTE_MAX_POINTS]; // 1064
} TrackRoute;

#define TROUTE_MEMORY_IMAGE_LOADED 0x01u
#define TROUTE_REVERSED            0x02u

#define TRACK_ROUTE_MAX_ROUTES 100

// 416 bytes on the disc, where the two bTLists are the manager's own first
// sixteen bytes and the routes are strung through them.
// `TheTrackRouteManager` at 0x0030c458.
//
// Here the lists are two arrays in insertion order, for the reason given on
// TrackRoute's node words. Nothing on the disc reads a route's Next or Prev
// except the two list walks and the unlink, so order and membership are the
// whole of the observable behaviour and both are kept exactly.
typedef struct TrackRouteManager {
    struct TrackRoute *pTrackRoutes[TRACK_ROUTE_MAX_ROUTES];
    struct TrackRoute *Racing[TRACK_ROUTE_MAX_ROUTES];
    struct TrackRoute *Traffic[TRACK_ROUTE_MAX_ROUTES];
    int                NumRacing;
    int                NumTraffic;
} TrackRouteManager;

extern TrackRouteManager TheTrackRouteManager;

// The record sizes are not a detail: a loaded route is the bundle's own
// bytes and the loader's stride is derived from them, so a compiler that
// laid any of these out differently would walk the chunk into the weeds
// rather than fail visibly.
typedef char trackroute_size_check[
    (sizeof(TrackRoutePoint) == 112 && sizeof(DrivingLineInfo) == 48 &&
     sizeof(Signpost) == 8 && sizeof(TrackRoute) == 115752) ? 1 : -1];

// -------------------------------------------------------- FindClosestPoint

// The `flags` argument both FindClosestPoints take. The disc passes integers
// at the call sites; these are the bits it actually tests.
#define TRFIND_AHEAD_ONLY   0x01  // keep only points the position is behind
#define TRFIND_POSTED_ONLY  0x02  // keep only Posted points
#define TRFIND_NO_HELISHEET 0x04  // reject points flagged NoHelisheet
#define TRFIND_SKIP_RACING  0x08  // manager only
#define TRFIND_SKIP_TRAFFIC 0x10  // manager only
#define TRFIND_BY_TRACK_DISTANCE 0x20  // measure with GetDistanceAway

// ------------------------------------------------------------ route points

// 0x001b7290. Note what it does *not* set: Position, Elevation, Direction,
// Length, the widths, DistanceAroundTrack, the driving lines and
// TheTerrainType are all left as they were. Only SignNumber (0xff),
// RoadBlockNumber (0x3f), RadarTrapNumber (0x3f), the three flags and the
// two slopes are written.
void trpoint_init(TrackRoutePoint *p);

// 0x001b72e0 / 0x001b7358. The point's local frame: `d` runs along
// Direction, `l` runs to its right as (Direction.y, -Direction.x). The 3D
// form adds ForwardSlope to the along axis and BankSlope to the lateral one,
// so the elevation follows the road's camber.
//
// The 3D original builds its two basis vectors on the stack and never writes
// their fourth lane, then does all the arithmetic with .xyzw VU0 ops, so the
// w it stores is whatever the stack held. This writes x, y and z and leaves
// `pad` alone, the same choice bvector.c makes.
void trpoint_get_position2(const TrackRoutePoint *p, bVector2 *o, float d,
                           float l);
void trpoint_get_position3(const TrackRoutePoint *p, bVector3 *o, float d,
                           float l);

// 0x001b73e0. Both clamped to [1, 64], and the argument order is
// (left, right) while the fields are stored right-then-left.
void trpoint_set_width(TrackRoutePoint *p, float left, float right);

// 0x001b7448. &SignpostArray[SignNumber], with no test for 0xff -- every
// caller checks first, and so must yours.
Signpost *trpoint_get_signpost(const TrackRoutePoint *p);

// 0x001b7460. Swaps the **first 48 bytes only**, so the driving-line tables
// and RouteNumber stay where they are while everything else moves. That is
// what makes ReverseRoute leave the driving lines to its own second pass.
void trpoint_swap_point_data(TrackRoutePoint *a, TrackRoutePoint *b);

// 0x001b74c0. Turns the point around: its position moves forward to where
// the next point's would be, the direction and both slopes negate, the two
// widths swap, the distance mirrors about the track length, and driving
// lines 0..9 swap with 10..19. Line 20 is untouched.
void trpoint_reverse_point(TrackRoutePoint *p);

// 0x001b75d8. The traffic version: just the distance mirror.
void trpoint_reverse_traffic_route_point(TrackRoutePoint *p);

// 0x001b75f0. Not a distance. It is
//
//   max(|Position - pos|, |CompareDistances(DistanceAroundTrack, d)| - 24)
//
// -- a point that is close in the plane but half a lap away still scores its
// track-distance error, which is what stops a search matching the other side
// of a hairpin.
float trpoint_get_distance_away(const TrackRoutePoint *p, const bVector2 *pos,
                                float d);

// Accessors that are inlined everywhere on the disc, recovered from a call
// site each. The offset is Q8 (0x00225064 shifts by 8 and scales by 2^-16)
// and the speed is a whole number in a byte (0x001b8238, same scale, shifted
// by 16).
float trpoint_get_driving_line_offset(const TrackRoutePoint *p, int line);
float trpoint_get_driving_line_speed(const TrackRoutePoint *p, int line);

static inline uint32_t trpoint_sign_number(const TrackRoutePoint *p)
{ return p->Bits & TRP_SIGN_MASK; }
static inline int trpoint_has_signpost(const TrackRoutePoint *p)
{ return (p->Bits & TRP_SIGN_MASK) != TRP_SIGN_MASK; }
static inline uint32_t trpoint_road_block_number(const TrackRoutePoint *p)
{ return (p->Bits & TRP_ROADBLOCK_MASK) >> TRP_ROADBLOCK_SHIFT; }
static inline uint32_t trpoint_radar_trap_number(const TrackRoutePoint *p)
{ return (p->Bits & TRP_RADARTRAP_MASK) >> TRP_RADARTRAP_SHIFT; }
static inline uint32_t trpoint_terrain_type(const TrackRoutePoint *p)
{ return (p->Bits & TRP_TERRAIN_MASK) >> TRP_TERRAIN_SHIFT; }
static inline int trpoint_is_posted(const TrackRoutePoint *p)
{ return (p->Bits & TRP_POSTED) != 0; }

// ------------------------------------------------------------------ routes

// 0x001b7660. Runs trpoint_init over all 1024 points, so it is only for a
// route built in memory; a loaded one never sees it.
void troute_init(TrackRoute *r, int routeNumber);

// 0x001b7760. Appends a point and returns it, or NULL when the table is
// full. The first point gets Direction (1, 0); from the second on, the
// *previous* point's direction is recomputed and copied forward, which means
// the last point in a route always carries the second-to-last one's.
TrackRoutePoint *troute_add_point(TrackRoute *r, const bVector2 *pos,
                                  float elevation, float leftWidth,
                                  float rightWidth);

// 0x001b7858. The neighbour in the table, or NULL at either end.
TrackRoutePoint *troute_get_relative_point(TrackRoute *r, TrackRoutePoint *p,
                                           int forward);

// 0x001b78d8. Points `p` at the next point and measures the gap. Returns 1
// when the gap is outside [4, 24] -- the editor's "this spacing is wrong"
// flag -- and 0 otherwise, including when `p` is the last point.
//
// It writes ForwardSlope to **both** points, p's and the next one's: the
// original is `p->ForwardSlope = next->ForwardSlope = dz / len`.
int troute_calculate_point_direction(TrackRoute *r, TrackRoutePoint *p);

// 0x001b79e0. Moves a point and re-derives the two directions either side.
//
// Elevation is taken from `pos->x`, not `pos->z`. That is the disc: two
// separate loads of 0(a2), the second of them into the elevation slot at
// 0x001b7a38. The port keeps it. Only TrackRouteEditor calls this.
int troute_move_point(TrackRoute *r, TrackRoutePoint *p, const bVector3 *pos);

// 0x001b7a90. Nearest point within `radius`, or NULL. `radius` is the
// running best, so it shrinks as the walk finds better ones.
//
// The walk is not exhaustive: after each point it skips
// `(int)(dist / 24) - 2` further ones when that is positive, on the argument
// that consecutive points are at most 24 apart. A point nearer than the one
// being measured cannot be inside the skipped run.
TrackRoutePoint *troute_find_closest_point(TrackRoute *r, const bVector2 *pos,
                                           float radius, int flags,
                                           float distanceAround);

// 0x001b7c78. The first point at or after `start` that `pos` has not passed,
// measured by the sign of the dot product with each point's direction.
TrackRoutePoint *troute_find_closest_point_ahead(TrackRoute *r,
                                                 const bVector2 *pos,
                                                 TrackRoutePoint *start);

// 0x001b7d28. Zeroes one driving line's offset and speed on every point,
// clears its IsValid and IsFake and sets LineTime to 999.
void troute_erase_driving_line(TrackRoute *r, int line);

// 0x001b8200. True when the middle point's speed for line 0 or line 1 is
// over 30. One sample, halfway along, is the whole test.
int troute_has_driving_line_data(const TrackRoute *r);

// 0x001b8280 / 0x001b84e8. Reverses a racing route -- the point order, each
// point, the DrivingLineInfo pairs 0..9 with 10..19, and the Reversed flag
// -- or, for a traffic route, only each point's distance around the track.
void troute_reverse_route(TrackRoute *r);
void troute_reverse_traffic_route(TrackRoute *r);

// 0x001b8548. Works out the stretch of track the route covers, by walking
// the points and watching the distance-around-track jump. A jump of more
// than half the track length means the route crosses the start line, so the
// distances get sorted into two buckets and the answer is the *gap* between
// them -- fStartDistance ends up greater than fEndDistance, which is the
// signal DistanceIsWithinRoute reads.
//
// Needs trackpath.h's distance, which is not ported; see there.
void troute_set_first_and_last(TrackRoute *r);

// 0x001b86c8. Inside [start, end], or outside (end, start) when the route
// wraps the start line.
int troute_distance_is_within_route(const TrackRoute *r, float d);

static inline TrackRoutePoint *troute_get_point(TrackRoute *r, int i)
{ return &r->TrackRoutePointTable[i]; }
static inline int troute_get_point_number(const TrackRoute *r,
                                          const TrackRoutePoint *p)
{ return (int)(p - r->TrackRoutePointTable); }

// ----------------------------------------------------------- the manager

// 0x001b8738. Both lists empty, both pointing at themselves, and the
// hundred-slot table cleared.
void trmgr_init(TrackRouteManager *m);

// 0x001b87e8. Files the route under its number and appends it to the list
// its Type asks for. A Type that is neither 0 nor 1 lands in the table and
// in no list.
void trmgr_add_route_to_right_list(TrackRouteManager *m, TrackRoute *r);

// 0x001b8848. Walks the 0x00034121 payload as a run of truncated memory
// images. Nothing is copied or allocated.
void trmgr_loader(TrackRouteManager *m, const uint8_t *chunk);

// 0x001b88e8. Unlinks and clears all hundred slots, freeing only routes that
// were built in memory rather than loaded.
void trmgr_unloader(TrackRouteManager *m);

// 0x001b8ce0. FindClosestPoint over the lists rather than one route.
TrackRoutePoint *trmgr_find_closest_point(TrackRouteManager *m,
                                          const bVector2 *pos, float radius,
                                          int flags, float distanceAround);

// 0x001b8a00. Reverses every route in the table: 50..69 as traffic, the rest
// as racing.
void trmgr_reverse_routes(TrackRouteManager *m);

static inline TrackRoute *trmgr_get_route(TrackRouteManager *m, int n)
{
    if (n < 0 || n >= TRACK_ROUTE_MAX_ROUTES) return 0;
    return m->pTrackRoutes[n];
}

// ---------------------------------------------------------------- signposts

// 0x001b6f60 / 0x001b6f88. The slot NewRoute names, and that route's point
// NewPoint. **The NULL test in the second is the port's own**: the image's
// guard is a `bltz` on a byte it loaded with `lbu`, so it never fires, and
// an empty slot gives `0 + 1064 + 112 * NewPoint`. No sign on the one track
// on hand names an empty slot (airoute_check hooks the case in the image).
// A NewRoute of 100 or more reads past the table on both sides.
TrackRoute      *signpost_get_new_route(const Signpost *s);
TrackRoutePoint *signpost_get_new_route_point(const Signpost *s);

// 0x001b7080. Route number under 50.
int signpost_is_racing_route(const Signpost *s);

// 0x001b6fc8. For each sign on a racing route: the point index mirrors and
// the Backwards bit flips.
void signpost_reverse_signs(void);

// 0x001b7090. Fills every sign's Distance from its point. Needs trackpath.
void signpost_set_distances(void);

// 0x001b7120. The first sign at or past `d`, or 0 when every sign is nearer
// than that -- so a distance past the last sign wraps to the first.
int signpost_get_index(float d);

// 0x001b8f20. Whether the 0x00034122 chunk was loaded.
int signposts_present(void);

// 0x001b7168. A debug walk whose only arithmetic -- the distance between a
// point and the point its signpost names -- is computed and then dropped.
// The asserts it fed were compiled out of the retail build and nothing calls
// it. Here so the object is complete.
void signpost_test_consistency(void);

// ------------------------------------------------------------- chunk hooks

#define CHUNK_TRACK_ROUTES    0x00034121u
#define CHUNK_TRACK_SIGNPOSTS 0x00034122u

// 0x001b8e60 / 0x001b8ec8. Return 1 when the chunk was theirs.
int track_routes_loader(const uint8_t *chunk);
int track_routes_unloader(const uint8_t *chunk);

// 0x001b9188, from EndGameFlowLoadingTrackSpecific (0x00164684). Reverses
// everything when `forward` is false, sets every route's first and last
// distance, then sorts the signposts by distance and rewrites every point's
// SignNumber through the new order.
void init_track_routes(int forward);

// 0x001b9428. Empty on the disc, and empty here.
void close_track_routes(void);

// 0x001b8f30. The object's own heapsort, over `n` elements of `size` bytes,
// ordered by the sign of `cmp`. Exported because it is a real function with
// a real symbol and the checker drives it directly.
typedef float (*HeapSortCompare)(const void *a, const void *b);
void heap_sort(void *base, int n, int size, HeapSortCompare cmp);

#endif
