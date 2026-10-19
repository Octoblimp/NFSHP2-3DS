// skids -- retail's skid marks, SkidSegment .. the clans, 0x001aa788 ..
// 0x001abaa0 (TASKS 78).
//
// A wheel that slides lays a trail: Wheel::MaybeMakeSkids gives its
// SkidMaker (Wheel+384, wheel.h) a point on the ground, a half-width across
// the trail, the terrain under it and how dark to make it, and MakeSkid
// adds the point to the maker's SkidSet. A set holds up to eight points,
// SkidSegments, each a position, its half-width in 1/64 m and an intensity.
// Points closer than 0.25 m together, or straight on from the last pair,
// move the last point instead of adding one. A turn of more than about 37
// degrees ends the set, and so does a change of terrain, a full set, or the
// car going out of view in a split screen; the next point starts a new one
// from the last, so the trail goes on unbroken.
//
// The sets come from a pool of 128 and sit on SkidSetList, most recently
// drawn first; a full pool frees the set at the tail. Each set is also on
// its clan's list: the clans are 64 m squares of the ground, by x and y, 40
// at most, kept most recently used first and freed from the tail, so the
// renderer can pass over whole squares it cannot see. World's snapshot
// flushes them all.
//
// Retail's SkidSet is the demo's with three fields more: the car the trail
// is under, whether that car is seen in both players' views, and the set's
// centre, which RenderSkids measures the camera's distance to. MakeSkid
// also lays nothing more than 4 m from the car.
//
// The drawing -- SkidSet::Render, RenderSkids, RenderClans -- is 78c's.
//
// Cross-check: tools/skids_check.py, against the retail image in mipsemu.
// Write-up: docs/formats/skids.md.

#ifndef SKIDS_H
#define SKIDS_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bplist.h"
#include "bslotpool.h"
#include "bvector.h"
#include "terraintype.h"
#include "texturepack.h"

struct Car;
struct SkidMaker;

// SkidSegment, 16 bytes (type#1016). DeltaPosition is the half-width, from
// the trail's centre to one edge, times 64.
typedef struct SkidSegment {
    float   Position[3];        //  0
    int8_t  DeltaPosition[3];   // 12
    uint8_t Intensity;          // 15  0..255
} SkidSegment;

#define SKIDSET_MAX_SEGMENTS 8

// SkidSet, retail's 272 bytes (the demo's type#1007 is 256). pCar,
// bVisibleToBothPlayers and Centre are retail's, unnamed; the names are
// the port's. bVisibleToBothPlayers is the car's VisibleViewBits bits 1
// and 2, players 1 and 2, both set, when the set was made.
typedef struct SkidSet {
    bNode             Node;                   //   0  bTNode<SkidSet>
    uint32_t          _pad8[2];               //   8
    bVector3          LastNormal;             //  16  the last pair's way
    float             LastSegmentLength;      //  32
    struct Car       *pCar;                   //  36
    int32_t           bVisibleToBothPlayers;  //  40
    struct Clan      *pClan;                  //  44
    bPNode           *pClanNode;              //  48  on the clan's list
    struct SkidMaker *pSkidMaker;             //  52  NULL once finished
    int32_t           TheTerrainType;         //  56
    uint32_t          _pad60;                 //  60
    bVector3          Position;               //  64  the first point
    bVector3          BBoxMax;                //  80
    bVector3          BBoxMin;                //  96
    SkidSegment       SkidSegments[SKIDSET_MAX_SEGMENTS]; // 112
    int32_t           NumSkidSegments;        // 240
    uint32_t          _pad244[3];             // 244
    bVector3          Centre;                 // 256  the box's
} SkidSet;                                    // 272

// Clan, 80 bytes (type#1001). Hash is the square's: see get_clan.
// LastUpdateTime is a WorldTime.
typedef struct Clan {
    bNode     Node;             //  0  bTNode<Clan>
    bNode     SkidSetList;      //  8  bPList<SkidSet>
    uint32_t  Hash;             // 16
    int32_t   LastUpdateTime;   // 20
    uint32_t  _pad24[2];        // 24
    bVector3  Position;         // 32  the first set's first point
    bVector3  BBoxMin;          // 48
    bVector3  BBoxMax;          // 64
} Clan;                         // 80

#if UINTPTR_MAX == 0xffffffffu
typedef char skids_layout_check[
    (sizeof(SkidSegment) == 16 && sizeof(SkidSet) == 272
     && offsetof(SkidSet, LastNormal) == 16
     && offsetof(SkidSet, pCar) == 36
     && offsetof(SkidSet, pSkidMaker) == 52
     && offsetof(SkidSet, Position) == 64
     && offsetof(SkidSet, BBoxMin) == 96
     && offsetof(SkidSet, SkidSegments) == 112
     && offsetof(SkidSet, NumSkidSegments) == 240
     && offsetof(SkidSet, Centre) == 256
     && sizeof(Clan) == 80
     && offsetof(Clan, Hash) == 16
     && offsetof(Clan, Position) == 32
     && offsetof(Clan, BBoxMax) == 64) ? 1 : -1];
#endif

#define SKIDSET_POOL_SLOTS 128
#define CLAN_POOL_SLOTS    40

// The image's globals. SkidSetList (gp-19208) and ClanList (gp-19160)
// start empty. SkidTextureInfo (0x00311520) is each terrain's skid
// texture, from InitSkids. PlotSkidsInCaffeine and
// PlotSkidPointsInCaffeine (the demo's names) are debug switches InitSkids
// clears and nothing reads.
extern bNode        SkidSetList;
extern BSlotPool   *SkidSetSlotPool;                     // gp-19200
extern int32_t      PlotSkidsInCaffeine;                 // gp-19196
extern int32_t      PlotSkidPointsInCaffeine;            // gp-19192
extern TextureInfo *SkidTextureInfo[NUM_TERRAIN_TYPES];
extern bNode        ClanList;
extern BSlotPool   *ClanSlotPool;                        // gp-19152

// ------------------------------------------------------------ SkidSegment

// SetPoints, 0x001aa788: the position, and each of the delta's three
// lanes times 64, truncated, as a byte.
void skid_segment_set_points(SkidSegment *s, const bVector3 *pos,
                             const bVector3 *delta);

// GetPoints, 0x001aa7f8: x, y and z of each, the delta only when it is not
// NULL. Neither's pad is written.
void skid_segment_get_points(const SkidSegment *s, bVector3 *pos,
                             bVector3 *delta);

// GetEndPoints, 0x001aa870: the position plus the delta, then minus it.
void skid_segment_get_end_points(const SkidSegment *s, bVector3 *a,
                                 bVector3 *b);

// ---------------------------------------------------------------- SkidSet

// SkidSet::SkidSet(SkidMaker *, Car *, bVector3 *, bVector3 *,
// TerrainType, float), 0x001aa8f8. Not linked onto SkidSetList: that is
// CreateNewSkidSet's. The car is read whatever it is; the port takes a
// NULL car as one seen nowhere. The box and the centre start at the
// point, the set goes on the tail of its clan's list (GetClan's, which may
// make the clan), and AddSegment adds the point.
SkidSet *skidset_construct(SkidSet *s, struct SkidMaker *maker,
                           struct Car *car, const bVector3 *pos,
                           const bVector3 *delta, int32_t terrain,
                           float intensity);

// _$_7SkidSet, 0x001aa9e0. A set its maker still holds has the maker's
// MakeNoSkid -- which finishes the maker's set, whichever that is now.
// Then off its clan's list, its node freed, and with bit 0 of `flags` the
// set freed to SkidSetSlotPool. The caller has it off SkidSetList.
void skidset_destroy(SkidSet *s, int32_t flags);

// AddSegment(bVector3 *, bVector3 *, float), 0x001aaa58. 1 when the set is
// full and nothing was added, else 0. With two segments or more, a way
// that turns from LastNormal by more than 0.2 in its cosine finishes the
// set and adds nothing; one that is the last pair's within 0.002, or that
// is under 0.25 m with the last pair's length, moves the last point,
// unless the two together pass 3 m. Each point sets the intensity (times
// 255, truncated), grows the set's box by the step's length about the
// point and the clan's box by the set's, and moves the centre.
int32_t skidset_add_segment(SkidSet *s, const bVector3 *pos,
                            const bVector3 *delta, float intensity);

// FinishedAddingSkids, 0x001aaca0: maker and set let go of each other.
void skidset_finished_adding_skids(SkidSet *s);

// The same, in the shape of physcomp.h's seam, gSkidSetFinishedAddingFn:
// a wheel's destructor finishes its maker's set.
void skidset_finished_adding_seam(void *s);

// GetLastPoints(bVector3 *, bVector3 *), 0x001ab4e8: the last segment's.
void skidset_get_last_points(const SkidSet *s, bVector3 *pos,
                             bVector3 *delta);

// CreateNewSkidSet(SkidMaker *, Car *, bVector3 *, bVector3 *,
// TerrainType, float), 0x001aae80. With the pool full, the set at
// SkidSetList's tail off it and destroyed with 3; then a set from the pool
// (bMalloc, the short path) on the list's head.
SkidSet *create_new_skid_set(struct SkidMaker *maker, struct Car *car,
                             const bVector3 *pos, const bVector3 *delta,
                             int32_t terrain, float intensity);

// SkidMaker::MakeSkid(Car *, bVector3 *, bVector3 *, TerrainType, float),
// 0x001aaf50. Nothing when the point is over 4 m from the car's
// GeometryPosition. With no set, a new one. Else the point goes on the
// set when the car's both-views bit and the terrain are the set's, and
// AddSegment takes it; otherwise -- a turn that finished the set aside --
// the set is finished and a new one starts from its last point, at its
// last intensity, and takes this one.
void skidmaker_make_skid(struct SkidMaker *m, struct Car *car,
                         const bVector3 *pos, const bVector3 *delta,
                         int32_t terrain, float intensity);

// SkidMaker::MakeNoSkid, 0x001ab0f8: the maker's set, if any, finished.
void skidmaker_make_no_skid(struct SkidMaker *m);

// InitSkids, 0x001ab118. The pool, if there is none: 128 of 272 bytes in
// memory pool 16, and not to grow. Then each terrain's skid texture, by
// its SkidTextureName's hash (GetTextureInfo with the default), or NULL
// with no name; and the two debug switches cleared. The World's
// constructor calls it (worldinit.c).
void init_skids(void);

// CloseSkids, 0x001ab1d0: the pool deleted and cleared, if there is one,
// and every texture forgotten. SkidSetList is left as it is: the World's
// destructor closes the clans first, and they delete every set.
void close_skids(void);

// DeleteThisSkid(SkidSet *), 0x001ab228: off SkidSetList and destroyed
// with 3.
void delete_this_skid(SkidSet *s);

// ------------------------------------------------------------------ Clan

// Clan::Clan(bVector3 *, unsigned int), 0x001ab910: an empty list, the
// position and hash, and the box at the point. LastUpdateTime is left as
// the pool gives it (bOMalloc clears the slot).
Clan *clan_construct(Clan *c, const bVector3 *pos, uint32_t hash);

// _$_4Clan, 0x001ab960: each set on its list deleted (DeleteThisSkid),
// from the head, and with bit 0 of `flags` the clan freed to ClanSlotPool.
// The caller has it off ClanList.
void clan_destroy(Clan *c, int32_t flags);

// Clan::ExpandBoundingBox(bVector3 *, bVector3 *), 0x001ab510: the clan's
// box grown by another's corners.
void clan_expand_bounding_box(Clan *c, const bVector3 *mn,
                              const bVector3 *mx);

// InitClans, 0x001ab618: the pool, if there is none: 40 of 80 bytes in
// memory pool 16. The World's constructor calls it.
void init_clans(void);

// FlushClans, 0x001ab650: every clan off ClanList from its head and
// destroyed with 3, and so every set. World::DoSnapshot calls it
// (worldsnap.c).
void flush_clans(void);

// CloseClans, 0x001ab6a0: with a pool, the clans flushed and the pool
// deleted and cleared. The World's destructor calls it.
void close_clans(void);

// GetClan(bVector3 *), 0x001ab6d0. The square's hash is y's and x's
// 64 m cell, (int)(v * 65536) >> 22, y's in the high half and x's low 16
// bits in the low. A clan of that hash goes to ClanList's head, stamped
// with WorldTime. Else a new one on the head, from the pool's full path,
// the tail's clan destroyed with 3 first when the pool is full.
Clan *get_clan(const bVector3 *pos);

#endif
