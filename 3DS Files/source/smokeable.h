// smokeable -- Smokeable.obj, retail 0x0021ec80 .. 0x002220e8: the
// breakable roadside objects (signs, fences, bins, cones, the roadblocks'
// barrels) and the helicopter's munitions' base class.
//
// A smokeable starts life as a VirginSmokeable: a static body with no
// physics, one for each spawner the track's data places (chunk 0x34027),
// built by SpawnSmokeables when the world is made. When a car's box first
// touches one, DynamicCollisionBody::MaybeCreateWitnesses converts it
// (ConvertToSmokeable): the virgin goes, and a Smokeable -- a dynamic body
// with a RigidBody of its own, a WorldObject to draw it and two lists of
// effect emitters -- takes its place. A smokeable that is struck hard
// enough to beat its AnchorStrength wakes and moves; one struck harder than
// its BreakingStrength comes apart into its children (Break). After two
// seconds untouched with no witnesses, one that never woke turns back into
// a virgin; one that woke dies when its Lifetime runs out.
//
// The kinds of smokeable are SmokeableInfos (chunk 0x34026), 224 bytes
// each, kept on SmokeableInfoList and found by their name's hash.

#ifndef SMOKEABLE_H
#define SMOKEABLE_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bmatrix.h"
#include "bslotpool.h"
#include "collisionbody.h"
#include "physicssystem.h"
#include "rigidbody.h"
#include "scenery.h"
#include "timer.h"
#include "topology.h"
#include "worldobject.h"

// 224 bytes, one for each kind of smokeable, kept on a list at gp-15848
// that FindSmokeableInfo (0x0021f8f8) walks by NameHash. From the stab,
//
//   SmokeableInfo:Tt289=s224!1,020,280;Name:...,64,192;RBI:...,256,640;...
//
// so a bTNode base at 0. The roadblock barrels' spawn (barricade.c) is the
// first reader: it scales RBI's mass and inertia tensor.
typedef struct SmokeableInfo {
    bNode    Node;                          //   0  bTNode<SmokeableInfo>
    char     Name[24];                      //   8
    RigidBodyInfo RBI;                      //  32
    uint32_t NameHash;                      // 112
    uint32_t AnchorEmitterGroupNameHash;    // 116
    uint32_t DynamicEmitterGroupNameHash;   // 120
    int32_t  NumChildren;                   // 124
    struct SmokeableInfo *pChildren[4];     // 128
    uint32_t ChildNameHashes[4];            // 144
    float    CenterOfMass[3];               // 160  twelve bytes in the stab
    float    Padding;                       // 172
    float    Lifetime;                      // 176
    float    AnchorStrength;                // 180
    float    BreakingStrength;              // 184
    float    Bounciness;                    // 188
    int32_t  TheTerrainType;                // 192
    uint32_t TerrainTypeHash;               // 196
    float    Friction;                      // 200
    float    Padding2;                      // 204  read as a word: nonzero
                                            //      keeps one from far-away
                                            //      deletion
    bNode    DynamicEmitterList;            // 208  bTList<AcidEmitter>
    bNode    AnchorEmitterList;             // 216
} SmokeableInfo;                            // 224

typedef char smokeableinfo_layout_check[
    (sizeof(void *) != 4
     || (offsetof(SmokeableInfo, RBI) == 32
         && offsetof(SmokeableInfo, NameHash) == 112
         && offsetof(SmokeableInfo, CenterOfMass) == 160
         && offsetof(SmokeableInfo, TheTerrainType) == 192
         && offsetof(SmokeableInfo, AnchorEmitterList) == 216
         && sizeof(SmokeableInfo) == 224)) ? 1 : -1];

// 8 bytes, the records of chunk 0x34027: a smokeable placed by the track,
// as the SmokeableInfo's name hash and the scenery instance it stands in
// for (whose position and rotation it takes).
typedef struct SmokeableSpawner {
    uint32_t SmokeableInfoHash;             // 0
    int16_t  ScenerySectionNumber;          // 4
    int16_t  SceneryInstanceNumber;         // 6
} SmokeableSpawner;                         // 8

typedef char smokeablespawner_layout_check[
    sizeof(SmokeableSpawner) == 8 ? 1 : -1];

// The smokeable before anything touches it, 100 bytes: a static body of
// type VIRGIN_SMOKEABLE_COLLISION_BODY with ID ~(spawner's index).
typedef struct VirginSmokeable {
    StaticCollisionBody Static;             //  0
    SmokeableSpawner *pSmokeableSpawner;    // 84
    SmokeableInfo    *pSmokeableInfo;       // 88
    SceneryInstance  *pSceneryInstance;     // 92
    SceneryInfo      *pSceneryInfo;         // 96
} VirginSmokeable;                          // 100

typedef char virginsmokeable_layout_check[
    (sizeof(void *) != 4
     || (offsetof(VirginSmokeable, pSmokeableSpawner) == 84
         && sizeof(VirginSmokeable) == 100)) ? 1 : -1];

// 1136 bytes. The stab is
//
//   Smokeable:Tt1521=s1136!2,020,1474;022048,757;...
//
// so two bases: DynamicCollisionBody at 0, and a PhysicsSystem at 256
// whose vptr (at 268) is a table of Smokeable's own, overriding
// ComputeAuxiliaries. World::DoTimestepCollisions reads BreakingStrength:
// ConsiderImpulse stores -1 there when an impulse breaks the smokeable.
typedef struct Smokeable {
    DynamicCollisionBody Dynamic;               //    0
    PhysicsSystem        System;                //  256  the second base
    SmokeableInfo       *SI;                    //  272
    float                AnchorStrength;        //  276  0 once loose
    float                BreakingStrength;      //  280  -1 once broken
    Timer                TimeCreated;           //  284
    Timer                TimeAwoken;            //  288
    Timer                TimeLastCarContact;    //  292
    SmokeableSpawner    *pSmokeableSpawner;     //  296  set while a virgin
                                                //       could come back
    float                GroundRaise;           //  300
    TopologyCoordinate   TC;                    //  304
    WorldObject          TheWorldObject;        // 1008
    bNode                AnchorEmitterList;     // 1104  bPList<AcidEmitter>
    bNode                DynamicEmitterList;    // 1112
    int8_t               AnchorEmittersAdded;   // 1120  0, 1 added, 2 fed
    int8_t               DynamicEmittersAdded;  // 1121
    int8_t               Awake;                 // 1122
    int8_t               Blinking;              // 1123
    uint8_t              _pad1124[12];          // 1124  the quadword round-up
} Smokeable;                                    // 1136

typedef char smokeable_layout_check[
    (offsetof(Smokeable, System) == sizeof(DynamicCollisionBody)
     && (sizeof(void *) != 4
         || (offsetof(Smokeable, System) == 256
             && offsetof(Smokeable, SI) == 272
             && offsetof(Smokeable, BreakingStrength) == 280
             && offsetof(Smokeable, pSmokeableSpawner) == 296
             && offsetof(Smokeable, TC) == 304
             && offsetof(Smokeable, TheWorldObject) == 1008
             && offsetof(Smokeable, AnchorEmitterList) == 1104
             && offsetof(Smokeable, Awake) == 1122
             && sizeof(Smokeable) == 1136))) ? 1 : -1];

// The tables. Smokeable's has two slots past CollisionBody's 26.
#define SMOKEABLE_VTABLE         0x002bcb10u
#define SMOKEABLE_SYSTEM_VTABLE  0x002bcaf0u
#define VIRGINSMOKEABLE_VTABLE   0x002bcbf0u
#define SMOKEABLE_VT_ENTRIES     28
#define SMOKEABLE_SYSTEM_VT_ENTRIES 4
#define SMOKEABLE_VT_GET_SMOKE_TYPE    208
#define SMOKEABLE_VT_ON_LIFETIME_END   216

// SmokeableType. The creators for 1 to 3 are the helicopter's munitions'.
#define ST_BASIC_SMOKEABLE      0
#define ST_ROCKET               1
#define ST_SMOKEBOMB            2
#define ST_DROPPED_SPIKES       3
#define ST_NUM_SMOKEABLE_TYPES  4

typedef Smokeable *(*SmokeableCreatorFn)(int32_t id, SmokeableInfo *info,
                                         uint32_t name_hash);

// SmokeableCreators, 0x0031c1e0.
extern SmokeableCreatorFn SmokeableCreators[ST_NUM_SMOKEABLE_TYPES];

// SmokeableInfoList, bTList<SmokeableInfo> at gp-15848. Its static
// initialiser points it at itself; the port's definition does the same.
extern bNode SmokeableInfoList;

// The spawners, gp-15860 and gp-15856: chunk 0x34027's records and count.
extern SmokeableSpawner *pSmokeableSpawners;
extern int32_t NumSmokeableSpawners;

// gp-15872 and gp-15868, made by SpawnSmokeables and deleted by
// ClearSmokeables: one virgin for each spawner, and 32 smokeables of 1136
// bytes.
extern BSlotPool *VirginSmokeableSlotPool;
extern BSlotPool *SmokeableSlotPool;

// gp-15864: how many smokeables are awake.
extern int32_t AwakeSmokeablesCount;

// Installs the three tables. The game calls it once at boot.
void smokeable_install_vtables(void);

// ------------------------------------------------------ the module

// RegisterSmokeableCreator, 0x0021ec80, and CreateSmokeable, 0x0021ec98:
// the creator for `type`, and a call to it.
void smokeable_register_creator(int32_t type, SmokeableCreatorFn fn);
Smokeable *smokeable_create(int32_t type, int32_t id, SmokeableInfo *info,
                            uint32_t name_hash);

// BasicSmokeableCreator, 0x0021ecd0: a Smokeable from the pool.
Smokeable *smokeable_basic_creator(int32_t id, SmokeableInfo *info,
                                   uint32_t name_hash);

// 0x0021ed28, unnamed. A smokeable of `type` standing on the ground at
// `pos`'s x and y, turned `ang` about the ground's normal: its id, or -1
// when there is no ground there or the pool is full. The roadblock's
// barrels are spawned this way.
int32_t smokeable_spawn(int32_t type, SmokeableInfo *info, uint32_t name_hash,
                        const bVector3 *pos, uint16_t ang);

// 0x0021eef8, unnamed. The same placed by a matrix: no ground search.
int32_t smokeable_spawn_matrix(int32_t type, SmokeableInfo *info,
                               uint32_t name_hash, const bMatrix4 *m);

// 0x0021ef88, unnamed. The smokeable with collision body id `id`, if it is
// still one of `info`'s, destroyed. A negative id does nothing.
void smokeable_delete(int32_t id, SmokeableInfo *info);

// GetSmokeableSpawner(int), 0x0021eff8, and its inverse at 0x0021f018.
SmokeableSpawner *smokeable_get_spawner(int32_t i);
int32_t smokeable_get_spawner_index(const SmokeableSpawner *s);

// SmokeableInfo::MemoryImageLoad, 0x0021f038: the terrain type matched
// from its hash, and both emitter lists made empty.
void smokeableinfo_memory_image_load(SmokeableInfo *si);

// LoaderSmokeables / UnloaderSmokeables, 0x0021f080 and 0x0021f1d0, chunk
// slot 27. Chunk 0x34026's records go on the list's tail, each loaded, and
// then every info's children are found by hash; 0x34027 is the spawners.
int smokeable_loader(uint8_t *chunk);
int smokeable_unloader(uint8_t *chunk);

// InitSmokeables, 0x0021f270. Each spawner's scenery instance's rotation
// orthonormalised and written back in units of 2^-14.
void init_smokeables(void);

// CloseSmokeables, 0x0021f500: empty.
void close_smokeables(void);

// DeleteSmokeableCollisionBodies, 0x0021f508: every Smokeable and
// VirginSmokeable body destroyed.
void delete_smokeable_collision_bodies(void);

// DeleteFarAwaySmokeableCollisionBodies, 0x0021f610. Smokeables going
// faster than 1000 or with a rotation's first element past 50 (the
// numbers have blown up); and, when fewer than 10 slots are free, ones
// asleep more than 45 s after waking and more than 120 from every player.
void delete_far_away_smokeable_collision_bodies(void);

// FindSmokeableInfo, 0x0021f8f8: the info with NameHash `hash`, or NULL.
SmokeableInfo *find_smokeable_info(uint32_t hash);

// SpawnSmokeables, 0x0021f930: the emitters for each info, the two
// pools, the basic creator, and a virgin for each spawner whose section
// is loaded and info is known (not one flagged 1 in a two-player race).
void spawn_smokeables(void);

// ClearSmokeables, 0x0021faa8: the bodies, the pools and the emitters.
void clear_smokeables(void);

// ConvertToSmokeable(CollisionBody *), 0x0021fe90: the virgin's
// Smokeable, and the virgin destroyed. collisionbody.c's
// gConvertToSmokeableFn.
CollisionBody *smokeable_convert_body(CollisionBody *b);

// --------------------------------------------------- VirginSmokeable

// 0x0021fee0 and 0x002200a0.
VirginSmokeable *virginsmokeable_init(VirginSmokeable *v,
                                      SmokeableSpawner *spawner);
void virginsmokeable_destroy(VirginSmokeable *v, int32_t flags);

// VirginSmokeable::ConvertToSmokeable, 0x00220178: a basic Smokeable in
// the virgin's place, raised off the ground if it would be in it; NULL
// when the pool is full.
Smokeable *virginsmokeable_convert(VirginSmokeable *v);

bVector3 *virginsmokeable_get_position(CollisionBody *b);     // 0x00222090
int32_t   virginsmokeable_get_terrain_type(CollisionBody *b); // 0x002220a0

// --------------------------------------------------------- Smokeable

// 0x002203c0 and 0x00220690.
Smokeable *smokeable_init(Smokeable *s, int32_t id, SmokeableInfo *info,
                          uint32_t name_hash);
void smokeable_destroy(Smokeable *s, int32_t flags);

// SetInitialPosition(bMatrix4 *, bVector3 *), 0x00220a00: the rigid
// body's state from the model's matrix (and a velocity, if given), the
// drawn matrix, the backup and the emitters.
void smokeable_set_initial_position(Smokeable *s, const bMatrix4 *m,
                                    const bVector3 *vel);

void smokeable_calibrate(Smokeable *s);                       // 0x00220c50
void smokeable_move(CollisionBody *b, float dt);              // 0x00220ce8
void smokeable_position_changed(Smokeable *s);                // 0x00220f80
void smokeable_service_emitters(Smokeable *s, const bMatrix4 *m);
                                                              // 0x00221060

// CheckTimers, 0x00221170. Returns 1 when it destroyed the smokeable,
// which Move then leaves alone (retail writes GroundRaise into the freed
// slot).
int32_t smokeable_check_timers(Smokeable *s);

void smokeable_activate_anchor_emitters(Smokeable *s);        // 0x002212d8
float smokeable_consider_impulse(CollisionBody *b, bVector3 *j,
                                 bVector3 *at);               // 0x00221340
void smokeable_consider_sleeping(Smokeable *s);               // 0x00221540
void smokeable_put_to_sleep(Smokeable *s);                    // 0x00221670
void smokeable_awaken(Smokeable *s);                          // 0x00221690

// Break(DynamicCollisionBody **), 0x00221748: a smokeable for each child,
// awake, written to `pieces`; this one destroyed. Returns the count.
int32_t smokeable_break(Smokeable *s, DynamicCollisionBody **pieces);

int32_t smokeable_does_child_art_exist(Smokeable *s);         // 0x00221868
int32_t smokeable_touching_car(Smokeable *s);                 // 0x00221ae8

void    smokeable_set_ground_raise(Smokeable *s, float r);    // 0x00221e68
float   smokeable_get_ground_raise(Smokeable *s);             // 0x00221e70
TopologyCoordinate *smokeable_get_topology_coordinate(Smokeable *s);
                                                              // 0x00221e78
float   smokeable_get_time_alive(Smokeable *s);               // 0x00221eb0
void    smokeable_set_blinking(Smokeable *s, int32_t on);     // 0x00221fd0

// The table's own methods.
bVector3 *smokeable_get_position(CollisionBody *b);           // 0x00222030
bVector3 *smokeable_get_velocity(CollisionBody *b);           // 0x00222020
bMatrix4 *smokeable_get_rotation(CollisionBody *b);           // 0x00222010
void      smokeable_apply_impulse(CollisionBody *b, bVector3 *j,
                                  bVector3 *at);              // 0x00221ff0
int32_t   smokeable_are_collisions_enabled(CollisionBody *b); // 0x00221fb8
int32_t   smokeable_get_terrain_type(CollisionBody *b);       // 0x00221f20
float     smokeable_get_mass_inverse(CollisionBody *b);       // 0x00221f88
bMatrix4 *smokeable_get_inertia_tensor_inverse(CollisionBody *b);
                                                              // 0x00221f58
int32_t   smokeable_is_moveable(CollisionBody *b);            // 0x00221f30
int32_t   smokeable_is_blinking(CollisionBody *b);            // 0x00221fd8
float     smokeable_get_bounciness(CollisionBody *b);         // 0x00221f10
float     smokeable_get_friction(CollisionBody *b);           // 0x00221f00
int32_t   smokeable_get_smoke_type(CollisionBody *b);         // 0x00222050
void      smokeable_on_lifetime_end(CollisionBody *b);        // 0x002212d0

// Smokeable::Break, through World::DoTimestepCollisions. main.c binds it
// to smokeable_break; a harness may leave it NULL, which aborts if a
// broken smokeable is reached.
extern int32_t (*gSmokeableBreakFn)(Smokeable *s,
                                    DynamicCollisionBody **pieces);

// DeleteFarAwaySmokeableCollisionBodies, which DoTimestepMove calls once
// every 128 world steps. A NULL seam is skipped.
extern void (*gDeleteFarAwaySmokeableCollisionBodiesFn)(void);

#endif
