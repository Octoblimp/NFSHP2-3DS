// collisionbody -- CollisionBody.obj (0x001ca170 .. 0x001cebb8): the
// collision bodies, the witnesses that pair them, the bookkeeping both
// keep, and the contacts a witness finds.
//
// A collision body is anything VClip can be asked about: a car, a
// smokeable, or a track polygon near a car. Each carries a convex
// polyhedron (vclip.h), a two-dimensional bounding box, and an ID below
// 206 that indexes a table of every body and a bit field of which pairs
// have a witness. The bodies are on one list, kept sorted by BBoxMax.x as
// the boxes move; a witness is a VCWitness for one pair, on a list of its
// own.
//
//   CollisionBody             84  abstract: bTNode, box, ID, counts, name
//   StaticCollisionBody       84  a body that does not move
//   TrackPolygonCollisionBody 1080 a TrackPolygon as a WaferPolyhedron
//   DynamicCollisionBody     256  a body that moves
//   CarCollisionBody         336  a car's (slice C)
//   CollisionBodyWitness     112  a VCWitness for two bodies
//   Contact                   64  two bodies VClip found overlapping
//
// This header has the eleventh slice of task 27 -- the NumberAllocator,
// Init and Close, the stats, the base class, the static and track-polygon
// bodies, the witness's constructor, destructor and bookkeeping, and the
// static initialiser and destructor -- and the twelfth, DynamicCollisionBody
// whole: its bounding volumes, its backup and interpolation, its physics
// pass-throughs, and the search that makes its witnesses and the track
// polygons' bodies near it -- and the thirteenth, CarCollisionBody whole,
// in carcollisionbody.c because it needs car.h -- and the fourteenth and
// fifteenth, in contact.c: the witness's TestForContact and its collision,
// and Contact whole. The bodies' and the witness's DoSnapshots are
// retail's (TASKS 72b); the witness's SnapshotEverything is the replay's
// and not here yet.
//
// Every record is the image's layout on the handheld. On a 64-bit host the
// pointers widen, and the asserts below allow for it: CB_AT(T, f, n, k) is
// offset n on the console plus k pointers' worth of slack.
//
// The stabs give the byte fields no sign. The code reads every one with
// `lb` and ID with `lh`, so here they are signed: Type is compared with 0
// and 3 and against a negative, the counts are tested against zero, and a
// negative ID is a body with no number.
//
// docs/formats/collision-body.md has the decode.

#ifndef COLLISIONBODY_H
#define COLLISIONBODY_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bslotpool.h"
#include "bvector.h"
#include "polyhedra.h"
#include "timer.h"
#include "topology.h"
#include "vclip.h"

// ------------------------------------------------------------ the records

// CollisionBodyType (.mdebug t1446).
#define CAR_COLLISION_BODY              0
#define SMOKEABLE_COLLISION_BODY        1
#define VIRGIN_SMOKEABLE_COLLISION_BODY 2
#define TRACK_POLYGON_COLLISION_BODY    3

// 206: the NumberAllocator's size, the table's length and the bit field's
// stride. Init hard-codes it three times over (206, 824, 5304).
#define COLLISIONBODY_MAX_BODIES 206

typedef struct CollisionBodyNode {
    struct CollisionBody *next;   // 0
    struct CollisionBody *prev;   // 4
} CollisionBodyNode;              // 8

//   CollisionBody:Tt4605=s84!1,020,4596         base bTNode<CollisionBody>
//
// The vptr is at 80 (`$vf4605:148,640`). The constructor sets everything
// but pPoly and Dynamic, which the derived classes do.
typedef struct CollisionBody {
    CollisionBodyNode Link;                     //  0  bTNode<CollisionBody>
    VCPolyhedron *pPoly;                        //  8
    int8_t    Type;                             // 12  *_COLLISION_BODY
    int8_t    Dynamic;                          // 13
    int16_t   ID;                               // 14  -1 for none
    int8_t    NumWitnesses;                     // 16
    int8_t    CollisionsDisabled;               // 17  a count, not a flag
    int8_t    NumCollisions;                    // 18
    int8_t    ActiveCollisionDetection;         // 19
    bVector2  BBoxMin;                          // 20
    bVector2  BBoxMax;                          // 28
    char      DebugName[40];                    // 36
    void     *pCaffeineObj;                     // 76
    uint32_t  _vtable;                          // 80
} CollisionBody;                                // 84

// StaticCollisionBody:Tt1557=s84!1,020,1456 -- no fields of its own.
typedef struct StaticCollisionBody {
    CollisionBody Body;                         //  0
} StaticCollisionBody;                          // 84

// TrackPolygonCollisionBody:Tt268=s1080!1,020,1557.
typedef struct TrackPolygonCollisionBody {
    StaticCollisionBody Static;                 //  0
    TrackPolygon   *pTP;                        // 84
    WaferPolyhedron Wafer;                      // 88
} TrackPolygonCollisionBody;                    // 1080

// DynamicCollisionBody:Tt1520=s256!1,020,4605. pTC is the car's own
// TopologyCoordinate (car.h, at 1280), which CreateTrackPolygonCollision
// Bodies searches; pSystem and pBody are the mover's PhysicsSystem and
// RigidBody while the car is in physics mode, NULL otherwise (carcollision
// body.c sets them up). The Backup fields are the body as BeginMove found
// it, and Interpolate blends back toward them.
typedef struct DynamicCollisionBody {
    CollisionBody Body;                         //   0
    int32_t   PhysicsMode;                      //  84
    TopologyCoordinate *pTC;                    //  88
    void     *pSystem;                          //  92  a PhysicsSystem
    void     *pBody;                            //  96  a RigidBody
    float     BackupTime;                       // 100
    uint8_t   _pad104[8];                       // 104  the quadword round-up
    bMatrix4  BackupRotation;                   // 112
    bVector3  BackupPosition;                   // 176
    bVector3  BackupVelocity;                   // 192
    float     CylinderBaseHeight;               // 208
    float     CylinderTopHeight;                // 212
    float     CylinderRadius;                   // 216
    float     Radius;                           // 220
    bVector3  LocalBBMin;                       // 224
    bVector3  LocalBBMax;                       // 240
} DynamicCollisionBody;                         // 256

// The PS2 aligns bMatrix4 to sixteen and puts eight bytes after BackupTime
// to get there; the port's bMatrix4 is float-aligned, so the eight bytes
// are written down or every field from BackupRotation on moves.
//
// CB_AT(T, f, n, k): offset n on the console, plus k pointers' worth of
// slack on a host with wider ones. The host adds four more for
// CollisionBody's tail padding, which is why PhysicsMode's k is five.
#define CB_SLACK ((size_t)(sizeof(void *) - 4))
#define CB_AT(T, f, n, k) (offsetof(T, f) == (size_t)(n) + (k) * CB_SLACK)
#define CB_ROUND(n) ((((size_t)(n)) + sizeof(void *) - 1) \
                     / sizeof(void *) * sizeof(void *))

typedef char collisionbody_layout_check[
    (CB_AT(CollisionBody, pPoly, 8, 2)
     && CB_AT(CollisionBody, Type, 12, 3)
     && CB_AT(CollisionBody, ID, 14, 3)
     && CB_AT(CollisionBody, ActiveCollisionDetection, 19, 3)
     && CB_AT(CollisionBody, BBoxMin, 20, 3)
     && CB_AT(CollisionBody, BBoxMax, 28, 3)
     && CB_AT(CollisionBody, DebugName, 36, 3)
     && CB_AT(CollisionBody, pCaffeineObj, 76, 3)
     && CB_AT(CollisionBody, _vtable, 80, 4)
     && sizeof(CollisionBody) == CB_ROUND(84 + 4 * CB_SLACK)) ? 1 : -1];

// pTP after CollisionBody's tail padding, then the Wafer after pTP: exact
// on the handheld; on the host, wherever the Wafer's own alignment puts it.
typedef char trackpolygoncollisionbody_layout_check[
    (CB_AT(TrackPolygonCollisionBody, pTP, 84, 5)
     && offsetof(TrackPolygonCollisionBody, Wafer)
        >= offsetof(TrackPolygonCollisionBody, pTP) + sizeof(void *)
     && (sizeof(void *) != 4
         || (offsetof(TrackPolygonCollisionBody, Wafer) == 88
             && sizeof(TrackPolygonCollisionBody) == 1080))) ? 1 : -1];

typedef char dynamiccollisionbody_layout_check[
    (CB_AT(DynamicCollisionBody, PhysicsMode, 84, 5)
     && CB_AT(DynamicCollisionBody, pTC, 88, 6)
     && CB_AT(DynamicCollisionBody, pSystem, 92, 7)
     && CB_AT(DynamicCollisionBody, pBody, 96, 8)
     && CB_AT(DynamicCollisionBody, BackupTime, 100, 9)
     && CB_AT(DynamicCollisionBody, BackupRotation, 112, 9)
     && CB_AT(DynamicCollisionBody, BackupPosition, 176, 9)
     && CB_AT(DynamicCollisionBody, Radius, 220, 9)
     && CB_AT(DynamicCollisionBody, LocalBBMax, 240, 9)
     && sizeof(DynamicCollisionBody) == CB_ROUND(256 + 9 * CB_SLACK))
    ? 1 : -1];

// Timer, the two stamps below, is timer.h's: Car's blink reaches
// Timer::SetTime, and RacingCar holds thirty-seven of them.

typedef struct CarCollisionBody {
    DynamicCollisionBody Dynamic;               //   0
    struct Car *pCar;                           // 256
    Timer     LastPenetrationTime;              // 260
    Timer     LastYawControlCollisionTime;      // 264
    // Retail's, in the demo's round-up, and the name is ours: its
    // constructor stamps it with WorldTimer beside the two above and the
    // replay moves it; nothing in the object reads it.
    Timer     ThirdTime;                        // 268
    bMatrix4  ScaledInverseInertiaTensor;       // 272
} CarCollisionBody;                             // 336

// DynamicCollisionBody is 256 + 9 slacks, 292 on the host, and a pointer's
// alignment rounds it to 296: so pCar lands ten slacks on, and the pointer
// itself makes the eleventh.
typedef char carcollisionbody_layout_check[
    (CB_AT(CarCollisionBody, pCar, 256, 10)
     && CB_AT(CarCollisionBody, LastPenetrationTime, 260, 11)
     && CB_AT(CarCollisionBody, LastYawControlCollisionTime, 264, 11)
     && CB_AT(CarCollisionBody, ThirdTime, 268, 11)
     && CB_AT(CarCollisionBody, ScaledInverseInertiaTensor, 272, 11)
     && sizeof(CarCollisionBody) == CB_ROUND(336 + 11 * CB_SLACK))
    ? 1 : -1];

typedef struct CollisionBodyWitnessNode {
    struct CollisionBodyWitness *next;          // 0
    struct CollisionBodyWitness *prev;          // 4
} CollisionBodyWitnessNode;                     // 8

struct Collision;

// CollisionBodyWitness:Tt1522=s112!2,020,1513;02128,1291 -- two bases,
// bTNode at 0 and VCWitness at 16, the eight bytes between them the
// VCWitness's quadword alignment. The four at the end are the record's.
typedef struct CollisionBodyWitness {
    CollisionBodyWitnessNode Link;              //   0  bTNode
    uint8_t   _pad8[8];                         //   8  the quadword round-up
    VCWitness Witness;                          //  16  the base
    CollisionBody *pBody1;                      //  96
    CollisionBody *pBody2;                      // 100
    struct Collision *pCollision;               // 104  NULL until it hits
    uint8_t   _pad108[4];                       // 108  the quadword round-up
} CollisionBodyWitness;                         // 112

typedef char collisionbodywitness_layout_check[
    (CB_AT(CollisionBodyWitness, Witness, 16, 2)
     && offsetof(CollisionBodyWitness, pBody1)
        == offsetof(CollisionBodyWitness, Witness) + sizeof(VCWitness)
     && (sizeof(void *) != 4
         || (offsetof(CollisionBodyWitness, pBody1) == 96
             && offsetof(CollisionBodyWitness, pCollision) == 104
             && sizeof(CollisionBodyWitness) == 112))) ? 1 : -1];

typedef struct ContactNode {
    struct Contact *next;                       // 0
    struct Contact *prev;                       // 4
} ContactNode;                                  // 8

// Contact:Tt2017=s64!1,020,2008. Two bodies VClip found overlapping, on
// World's list of them: how far back they first touched, the witness that
// found them, and the push that parts them there. The constructor leaves
// the links to the list and the push zero when the bodies part at once.
typedef struct Contact {
    ContactNode Link;                           //  0  bTNode<Contact>
    float     BackupTime;                       //  8
    CollisionBody *pBody1;                      // 12
    CollisionBody *pBody2;                      // 16
    CollisionBodyWitness *pWitness;             // 20
    uint8_t   _pad24[8];                        // 24  the quadword round-up
    bVector3  CrowbarVector;                    // 32
    int32_t   LoopFound;                        // 48  WorldLoopCounter
    uint8_t   _pad52[12];                       // 52  the quadword round-up
} Contact;                                      // 64

typedef char contact_layout_check[
    (CB_AT(Contact, BackupTime, 8, 2)
     && CB_AT(Contact, pBody1, 12, 3)
     && CB_AT(Contact, pBody2, 16, 4)
     && CB_AT(Contact, pWitness, 20, 5)
     && CB_AT(Contact, CrowbarVector, 32, 6)
     && CB_AT(Contact, LoopFound, 48, 6)
     && sizeof(Contact) == CB_ROUND(64 + 6 * CB_SLACK)) ? 1 : -1];

// NumberAllocator:Tt3780=s12. A bit per number, and the lowest clear one.
typedef struct NumberAllocator {
    int32_t  MaxNumbers;                        // 0
    uint8_t *pAllocatedBitField;                // 4
    int32_t  LowestFreeNumber;                  // 8
} NumberAllocator;                              // 12

// CollisionStats:Tt1440=s72. Nine counts, then the highest each has been.
// Every constructor bumps its class's count and its highest; every
// destructor drops the count. Nothing reads them.
typedef struct CollisionStats {
    int32_t NumCollisionBodyWitnesses;                  //  0
    int32_t NumCollisions;                              //  4
    int32_t NumCollisionBodies;                         //  8
    int32_t NumStaticCollisionBodies;                   // 12
    int32_t NumDynamicCollisionBodies;                  // 16
    int32_t NumTrackPolygonCollisionBodies;             // 20
    int32_t NumCarCollisionBodies;                      // 24
    int32_t NumVirginSmokeableCollisionBodies;          // 28
    int32_t NumSmokeableCollisionBodies;                // 32
    int32_t HighestNumCollisionBodyWitnesses;           // 36
    int32_t HighestNumCollisions;                       // 40
    int32_t HighestNumCollisionBodies;                  // 44
    int32_t HighestNumStaticCollisionBodies;            // 48
    int32_t HighestNumDynamicCollisionBodies;           // 52
    int32_t HighestNumTrackPolygonCollisionBodies;      // 56
    int32_t HighestNumCarCollisionBodies;               // 60
    int32_t HighestNumVirginSmokeableCollisionBodies;   // 64
    int32_t HighestNumSmokeableCollisionBodies;         // 68
} CollisionStats;                                       // 72

// ------------------------------------------------------------- the tables

// Twenty-six entries each: the empty one, then the destructor, DoSnapshot
// and twenty-three methods. The base's are `__pure_virtual` but for its
// destructor, DoSnapshot and IsBlinking; StaticCollisionBody fills all but
// GetPosition and GetTerrainType; TrackPolygonCollisionBody fills those
// two, its destructor and its DoSnapshot and takes the rest from Static.
// Slot 136 is `AreCollisionsEnabled__16Car
// CollisionBody` (0x001cdb50) in the car's table, which is the one every
// Car's body carries: two global switches first, then `CollisionsDisabled
// == 0`. Car::IsCollideable is its one caller in Car.obj.
#define COLLISIONBODY_VTABLE             0x0029bf48u
#define STATICCOLLISIONBODY_VTABLE       0x0029be78u
#define TRACKPOLYGONCOLLISIONBODY_VTABLE 0x0029bda8u
// DynamicCollisionBody's leaves GetPosition, GetVelocity, GetRotation,
// Move, ConsiderImpulse, AreCollisionsEnabled, GetTerrainType, IsMoveable,
// GetBounciness and GetFriction pure; the car's fills them.
#define DYNAMICCOLLISIONBODY_VTABLE      0x0029bcd8u
#define CARCOLLISIONBODY_VTABLE          0x0029bc08u
#define COLLISIONBODY_VT_ENTRIES         26

#define COLLISIONBODY_VT_DESTROY                       8
#define COLLISIONBODY_VT_DO_SNAPSHOT                  16
#define COLLISIONBODY_VT_GET_POSITION                 24
#define COLLISIONBODY_VT_GET_VELOCITY                 32
#define COLLISIONBODY_VT_GET_ROTATION                 40
#define COLLISIONBODY_VT_SET_POSITION                 48
#define COLLISIONBODY_VT_GET_MAX_BACKUP_TIME          56
#define COLLISIONBODY_VT_MOVE                         64
#define COLLISIONBODY_VT_BACKUP                       72
#define COLLISIONBODY_VT_INTERPOLATE                  80
#define COLLISIONBODY_VT_RECOMPUTE_AUXILLIARIES       88
#define COLLISIONBODY_VT_GET_CURRENT_VELOCITIES       96
#define COLLISIONBODY_VT_GET_TEST_IMPULSE_VELOCITIES 104
#define COLLISIONBODY_VT_SET_TO_PHYSICS_MODE         112
#define COLLISIONBODY_VT_CONSIDER_IMPULSE            120
#define COLLISIONBODY_VT_APPLY_IMPULSE               128
#define COLLISIONBODY_VT_ARE_COLLISIONS_ENABLED      136
#define COLLISIONBODY_VT_GET_TERRAIN_TYPE            144
#define COLLISIONBODY_VT_GET_MASS_INVERSE            152
#define COLLISIONBODY_VT_GET_INERTIA_TENSOR_INVERSE  160
#define COLLISIONBODY_VT_IS_MOVEABLE                 168
#define COLLISIONBODY_VT_CHANGE_IN_ENERGY            176
#define COLLISIONBODY_VT_IS_BLINKING                 184
#define COLLISIONBODY_VT_GET_BOUNCINESS              192
#define COLLISIONBODY_VT_GET_FRICTION                200

// Registers the base's, StaticCollisionBody's, TrackPolygonCollisionBody's
// and DynamicCollisionBody's tables.
void collisionbody_install_vtables(void);

// Registers the car's, which is carcollisionbody.c's.
void carcollisionbody_install_vtable(void);

// ------------------------------------------------------------ the globals

// 0x00311ca0.
extern CollisionStats TheCollisionStats;

// 0x00311cf0, 0x00311d00, 0x00311d40. What the static bodies hand out for
// their velocity, rotation and inertia: zero, identity, zero. Init makes
// the two matrices; the static initialiser zeroes the vector's x, y and z.
extern bVector3 ZeroVector;
extern bMatrix4 IdentityMatrix;
extern bMatrix4 ZeroMatrix;

// 0x00324418 and 0x00324440. Every body, sorted by BBoxMax.x, smallest
// first (ties by ID, the lowest first); every witness, oldest first. Both
// are zero on the disc -- not even pointing at themselves -- until the
// static initialiser.
extern CollisionBodyNode        CollisionBodyList;
extern CollisionBodyWitnessNode CollisionBodyWitnessList;

// 0x00324410 and 0x0032443c. Made by Init: the body with each ID, and the
// allocator of IDs.
extern CollisionBody  **pCollisionBodyTable;
extern NumberAllocator *pCollisionBodyNumberAllocator;

// 0x00324420, `_13CollisionBody$MaxCollisionBodyWidthX`: the widest
// BBoxMax.x - BBoxMin.x any body has had, kept up as the boxes change.
extern float MaxCollisionBodyWidthX;

// 0x00324464, `_20CollisionBodyWitness$pWitnessExistanceBitField`: bit
// ID1 * 206 + ID2 is set while bodies ID1 and ID2 have a witness, and so
// is ID2 * 206 + ID1.
extern uint8_t *pWitnessExistanceBitField;

// 0x00324468, 0x0032446c, 0x00324470. Made by Init.
extern BSlotPool *TrackPolygonCollisionBodySlotPool;
extern BSlotPool *CarCollisionBodySlotPool;
extern BSlotPool *CollisionBodyWitnessSlotPool;

// The allocations Init makes are the image's, and two of them are short.
// The bit field's 5304 bytes hold 42432 of the 42436 bits a 206-square
// takes, so the pairs (205, 202) to (205, 205) are in a 5305th byte; and
// SetMaxNumbers takes n >> 3 bytes, which for 206 numbers leaves 200 to
// 205 in a twenty-sixth. On the console both land in bMalloc's round-up
// to sixteen. The port asks for the byte more and zeroes it.
#define COLLISIONBODY_BITFIELD_BYTES 5304
#define COLLISIONBODY_SHORT_SLACK    1

// Collision.obj's destructor (0x0020b358), which EndCollision calls: a
// witness with a collision is ended through this. collision.c has it, and
// main.c points this at it; it stays a pointer so the checkers that link
// collisionbody.c need not link collision.c. A NULL seam aborts.
extern void (*gCollisionDestroyFn)(struct Collision *c, int32_t flags);

// Smokeable.obj's ConvertToSmokeable (0x0020c338), which MaybeCreateWitnesses
// calls on a virgin smokeable's body before it pairs with one: the body to
// pair with instead, or NULL for none. Not ported yet, and a NULL seam
// aborts -- nothing in the port makes a smokeable yet.
extern CollisionBody *(*gConvertToSmokeableFn)(CollisionBody *b);

// 0x001ce548, _GLOBAL_$I$TheCollisionStats: both lists empty, ZeroVector's
// x, y and z zeroed.
void collisionbody_static_init(void);

// 0x001ce520, _GLOBAL_$D$TheCollisionStats: destroys every witness, then
// every body through its table, each unlinked first.
void collisionbody_static_close(void);

// ------------------------------------------------------- NumberAllocator

// 0x001cb580. Frees any field there was, then takes n >> 3 bytes (plus
// the slack above) zeroed, with every number free. 0 leaves none.
void numberallocator_set_max_numbers(NumberAllocator *na, int32_t n);

// 0x001cb618. The lowest free number, taken; -1 when there is none.
int32_t numberallocator_allocate(NumberAllocator *na);

// 0x001cb658. Takes number i. When i was the lowest free, the lowest is
// found again from i + 1 up, and is MaxNumbers when none is.
void numberallocator_allocate_number(NumberAllocator *na, int32_t i);

// 0x001cb718. Frees i, which becomes the lowest free if it is lower.
void numberallocator_free_number(NumberAllocator *na, int32_t i);

// 0x001ce590. SetMaxNumbers(0), and bFree when flags & 1.
void numberallocator_destroy(NumberAllocator *na, int32_t flags);

// ----------------------------------------------------------- Init / Close

// 0x001cb760. The three pools (cars 14, track polygons 160, witnesses
// 256), the allocator for 206, the table, the two matrices and the bit
// field. EndGameFlowLoadingTrackSpecific is the one caller.
void init_collision_body(void);

// 0x001cb880. Deletes the pools, the allocator, the table and the bit
// field, and leaves every pointer NULL.
void close_collision_body(void);

// --------------------------------------------------------- CollisionBody

// 0x001cc2e8. `id` below 0 takes no number; otherwise the number is taken
// and the table points at b. On the list at the head, the box at
// -9999999 all four ways, the name empty and the four counts zero.
CollisionBody *collisionbody_init(CollisionBody *b, int32_t id,
                                  int32_t type);

// 0x001cc3b0. Off the list; every witness that has b ends with it; the
// number goes back. bFree when flags & 1.
void collisionbody_destroy(CollisionBody *b, int32_t flags);

// Retail's 0x001d6a98, slot 16. No section: CollisionsDisabled and
// ActiveCollisionDetection as one byte, the first in the low four bits;
// then, checksumming only, ID, Type and Dynamic.
struct ReplaySnapshot;
void collisionbody_do_snapshot(CollisionBody *b, struct ReplaySnapshot *s);

// 0x001cc530. The list's order: 1 when a's BBoxMax.x is the greater, and
// on a tie (or a NaN) when b's ID is below a's.
int32_t collisionbody_flip_function(const CollisionBody *a,
                                    const CollisionBody *b);

// 0x001cc578. Keeps MaxCollisionBodyWidthX up as b's width becomes w.
void collisionbody_update_max_width(CollisionBody *b, float w);

// 0x001cc630. The new box, and b moved along the list to where its
// BBoxMax.x now sorts -- unless BBoxMax.x has not changed.
void collisionbody_set_bbox_min_max(CollisionBody *b, const bVector2 *min,
                                    const bVector2 *max);

// 0x001cc748. Empty on the disc.
void collisionbody_plot_to_caffeine(CollisionBody *b, const bMatrix4 *m,
                                    const bVector3 *t);

// 0x001cc758. The allocator's lowest free number, read as a halfword.
int32_t collisionbody_get_next_id(void);

// 0x001cc768. bStrNCpy's forty bytes, the last forced to NUL.
void collisionbody_set_debug_name(CollisionBody *b, const char *name);

// 0x001cc798 and 0x001cc7a0. Empty.
void collisionbody_debug_print(CollisionBody *b);
void collisionbody_maybe_print_all(void);

// 0x001cc820. pCollisionBodyTable[i].
CollisionBody *collisionbody_find(int32_t i);

// 0x001cc838. The collision of b's i-th witness that has one, oldest
// first; NULL when i is not below NumCollisions.
struct Collision *collisionbody_get_collision(CollisionBody *b, int32_t i);

// 0x001cea70 and 0x001cea90. Disabling counts up; enabling counts down,
// and not below zero.
void collisionbody_enable_collisions(CollisionBody *b);
void collisionbody_disable_collisions(CollisionBody *b);

// 0x001ceaa0, slot 184. Only a car blinks.
int32_t collisionbody_is_blinking(CollisionBody *b);

// 0x001ceaa8 and 0x001ceb20. Whether b's box and [min, max], or other's
// box, overlap with `margin` to spare, inclusive.
int32_t collisionbody_do_bbox_check(const CollisionBody *b,
                                    const bVector2 *min, const bVector2 *max,
                                    float margin);
int32_t collisionbody_do_bbox_check_body(const CollisionBody *b,
                                         const CollisionBody *other,
                                         float margin);

// 0x001cea50 .. 0x001cebb0, the inline accessors.
static inline bVector2 *collisionbody_get_bbox_max(CollisionBody *b)
{
    return &b->BBoxMax;
}
static inline bVector2 *collisionbody_get_bbox_min(CollisionBody *b)
{
    return &b->BBoxMin;
}
static inline int32_t collisionbody_get_num_collisions(const CollisionBody *b)
{
    return b->NumCollisions;
}
static inline VCPolyhedron *collisionbody_get_poly(const CollisionBody *b)
{
    return b->pPoly;
}
static inline char *collisionbody_get_debug_name(CollisionBody *b)
{
    return b->DebugName;
}
static inline int32_t collisionbody_does_active_collision_detection(
    const CollisionBody *b)
{
    return b->ActiveCollisionDetection;
}
static inline int32_t collisionbody_get_id(const CollisionBody *b)
{
    return b->ID;
}
static inline int32_t collisionbody_is_dynamic(const CollisionBody *b)
{
    return b->Dynamic;
}

// ---------------------------------------------------- StaticCollisionBody

// 0x001cdf48 and 0x001cdfa8.
StaticCollisionBody *staticcollisionbody_init(StaticCollisionBody *s,
                                              int32_t id, int32_t type);
void staticcollisionbody_destroy(StaticCollisionBody *s, int32_t flags);

// Retail's 0x001d8760, slot 16: a jump to collisionbody_do_snapshot.
void staticcollisionbody_do_snapshot(CollisionBody *b,
                                     struct ReplaySnapshot *s);

// The table's methods (0x001ce8e8 .. 0x001cea30). A static body does not
// move and cannot be pushed: no velocity, no mass inverse, identity
// rotation, impulses considered in full and ignored.
bVector3 *staticcollisionbody_get_velocity(CollisionBody *b);
bMatrix4 *staticcollisionbody_get_rotation(CollisionBody *b);
void      staticcollisionbody_set_position(CollisionBody *b, bVector3 *p);
float     staticcollisionbody_get_max_backup_time(CollisionBody *b);
void      staticcollisionbody_move(CollisionBody *b, float t);
void      staticcollisionbody_backup(CollisionBody *b, float t);
void      staticcollisionbody_interpolate(CollisionBody *b, bVector3 *pos,
                                          bMatrix4 *rot, float t);
void      staticcollisionbody_recompute_auxilliaries(CollisionBody *b);
void      staticcollisionbody_get_current_velocities(CollisionBody *b,
                                                     bVector3 *v,
                                                     bVector3 *w);
void      staticcollisionbody_get_test_impulse_velocities(CollisionBody *b,
                                                          bVector3 *v,
                                                          bVector3 *w,
                                                          bVector3 *a,
                                                          bVector3 *c);
void      staticcollisionbody_set_to_physics_mode(CollisionBody *b,
                                                  CollisionBody *other);
float     staticcollisionbody_consider_impulse(CollisionBody *b,
                                               bVector3 *point,
                                               bVector3 *impulse);
void      staticcollisionbody_apply_impulse(CollisionBody *b,
                                            bVector3 *point,
                                            bVector3 *impulse);
int32_t   staticcollisionbody_are_collisions_enabled(CollisionBody *b);
float     staticcollisionbody_get_mass_inverse(CollisionBody *b);
bMatrix4 *staticcollisionbody_get_inertia_tensor_inverse(CollisionBody *b);
int32_t   staticcollisionbody_is_moveable(CollisionBody *b);
float     staticcollisionbody_change_in_energy(CollisionBody *b,
                                               bVector3 *point,
                                               bVector3 *impulse);
float     staticcollisionbody_get_bounciness(CollisionBody *b);
float     staticcollisionbody_get_friction(CollisionBody *b);

// ---------------------------------------------- TrackPolygonCollisionBody

// 0x001ce020. Static type 3, named "TrackPolygon<n>" for p's index in the
// tree's table, holding a reference to p's TrackPolygon (which points
// back), with the Wafer built from it at the origin and the box its box.
TrackPolygonCollisionBody *trackpolygoncollisionbody_init(
    TrackPolygonCollisionBody *t, int32_t id, TopologyTreePolygon *p);

// 0x001ce138. The reference given back, then Static's destructor; the
// slot back to the pool when flags & 1.
void trackpolygoncollisionbody_destroy(TrackPolygonCollisionBody *t,
                                       int32_t flags);

// 0x001ce8c8 and 0x001ce8b8, operator new and delete: the pool.
void *trackpolygoncollisionbody_new(void);
void  trackpolygoncollisionbody_delete(void *p);

// Retail's 0x001d8918, slot 16: a section for the body named
// "TrackPolygonCollisionBody" around Static's, then, checksumming, the
// box.
void trackpolygoncollisionbody_do_snapshot(CollisionBody *b,
                                           struct ReplaySnapshot *s);

// 0x001ce3d0, 0x001ce3e0, 0x001ce8b0.
bVector3     *trackpolygoncollisionbody_get_position(CollisionBody *b);
int32_t       trackpolygoncollisionbody_get_terrain_type(CollisionBody *b);
TrackPolygon *trackpolygoncollisionbody_get_track_polygon(
    TrackPolygonCollisionBody *t);

// --------------------------------------------------- DynamicCollisionBody
//
// The methods the table points at take the base, as the table calls them;
// the rest take the class.

// 0x001cc8a8. The base's constructor, then the class's table, pTC, Dynamic
// set, and pSystem, pBody and PhysicsMode zero. The rest -- pPoly, the
// backup, the volumes -- is the derived class's to fill.
DynamicCollisionBody *dynamiccollisionbody_init(DynamicCollisionBody *d,
                                                int32_t id, int32_t type,
                                                TopologyCoordinate *tc);

// 0x001cc928. The count down, then the base's destructor.
void dynamiccollisionbody_destroy(DynamicCollisionBody *d, int32_t flags);

// Retail's 0x001d7050, slot 16: a section for the body named
// "DynamicCollisionBody" around the base's, PhysicsMode's first byte, the
// topology's interest box cleared when taking or restoring, the volumes
// when checksumming, and the backup cleared when taking or restoring.
void dynamiccollisionbody_do_snapshot(CollisionBody *b,
                                      struct ReplaySnapshot *s);

// 0x001cca58. Over pPoly's vertices: the box, the sphere's radius about
// the origin, and a vertical cylinder -- the widest radius in x and y, the
// highest and lowest z. Every accumulator starts at zero, so the origin is
// always inside all three; the cylinder is then grown by 0.05 all round.
// The box's pad lanes are left as they were.
void dynamiccollisionbody_build_bounding_volumes(DynamicCollisionBody *d);

// 0x001ccbf0. The two-dimensional box, the cylinder's square about the
// position, handed to SetBBoxMinMax.
void dynamiccollisionbody_update_position(DynamicCollisionBody *d);

// 0x001ccc68. The rotation, position and velocity as they are, all sixteen
// bytes of each row and vector, and `t` as BackupTime.
void dynamiccollisionbody_begin_move(DynamicCollisionBody *d, float t);

// 0x001ccd08, slot 80. `t` seconds back toward the backup: each of the
// position and the rotation's rows is `(now - backup) * f + backup`, all
// four lanes, with f = (BackupTime - t) / BackupTime. A BackupTime below
// 1e-6 (a NaN is not below it) gives the body as it is.
void dynamiccollisionbody_interpolate(CollisionBody *b, bVector3 *pos,
                                      bMatrix4 *rot, float t);

// 0x001cceb0. The same for the velocity.
void dynamiccollisionbody_interpolate_velocity(DynamicCollisionBody *d,
                                               bVector3 *out, float t);

// 0x001ccf60, slot 72. The body put back `t` seconds: the table's
// Interpolate and InterpolateVelocity, written into the RigidBody's state
// as its position, orientation and momentum (the velocity times its Mass,
// all four lanes).
void dynamiccollisionbody_backup(CollisionBody *b, float t);

// 0x001cd010, slot 88. pSystem's ComputeAuxiliaries, through its table.
void dynamiccollisionbody_recompute_auxilliaries(CollisionBody *b);

// 0x001cd040 and 0x001cd060, slots 96 and 104. The RigidBody's velocities,
// and what they would be after impulse j at `at`.
void dynamiccollisionbody_get_current_velocities(CollisionBody *b,
                                                 bVector3 *v, bVector3 *w);
void dynamiccollisionbody_get_test_impulse_velocities(CollisionBody *b,
                                                      bVector3 *v,
                                                      bVector3 *w,
                                                      bVector3 *j,
                                                      bVector3 *at);

// 0x001cd078. The bodies either side along the list that might touch this
// one's box widened by `margin`: *first is the nearest body before it that
// ends before that box starts, *last the nearest after it that starts past
// its end, either the list head when there is none. Both bounds are
// exclusive; nothing calls it.
void dynamiccollisionbody_get_local_collision_bodies(DynamicCollisionBody *d,
                                                     float margin,
                                                     CollisionBody **first,
                                                     CollisionBody **last);

// 0x001cd130. With collisions enabled: the track polygons' bodies first,
// then a witness with every body whose box touches this one's that has
// none yet and has collisions enabled -- a virgin smokeable converted
// first, and the converted body's box looked at again. The search runs
// from the first body before this one that ends before it starts, up to
// the first after it that ends further than the widest body past its end.
void dynamiccollisionbody_maybe_create_witnesses(DynamicCollisionBody *d);

// 0x001cd3a0. A TrackPolygonCollisionBody for each of pTC's polygons that
// has none, touches this body's box and passes TrackPolygonCheck -- the
// first 48 such in pTC's order, then made in the order of their tree
// polygons' addresses, each with the lowest free ID. Returns how many it
// made: all of those, unless the pool fills first.
int32_t dynamiccollisionbody_create_track_polygon_collision_bodies(
    DynamicCollisionBody *d);

// 0x001cd5f0. Whether the polygon's plane passes within the cylinder: the
// distance from it to the position, against the cylinder's reach toward
// it -- the height (the top when the body faces the plane from behind or
// is behind it, the base otherwise) times |cos| of the tilt, plus the
// radius times its sine. The sine is ee_sqrt's, which a cosine rounded
// past one needs.
int32_t dynamiccollisionbody_track_polygon_check(DynamicCollisionBody *d,
                                                 TrackPolygon *tp);

// 0x001cd710, slot 176. The RigidBody's energy after impulse j at `at`,
// less its energy now.
float dynamiccollisionbody_change_in_energy(CollisionBody *b, bVector3 *j,
                                            bVector3 *at);

// 0x001ce820 .. 0x001ce870, the inline ones: GetBoundingBox (the local box,
// all sixteen bytes of each), and slots 128, 160, 152, 112, 56 and 48.
// ApplyImpulse is the RigidBody's; SetToPhysicsMode is empty; SetPosition
// stores all sixteen bytes through GetPosition.
void      dynamiccollisionbody_get_bounding_box(DynamicCollisionBody *d,
                                                bVector3 *min, bVector3 *max);
void      dynamiccollisionbody_apply_impulse(CollisionBody *b, bVector3 *j,
                                             bVector3 *at);
bMatrix4 *dynamiccollisionbody_get_inertia_tensor_inverse(CollisionBody *b);
float     dynamiccollisionbody_get_mass_inverse(CollisionBody *b);
void      dynamiccollisionbody_set_to_physics_mode(CollisionBody *b,
                                                   CollisionBody *other);
float     dynamiccollisionbody_get_max_backup_time(CollisionBody *b);
void      dynamiccollisionbody_set_position(CollisionBody *b, bVector3 *p);

// --------------------------------------------------- CollisionBodyWitness

// 0x001cb8f0. A VCWitness for the two bodies' polyhedra, at the tail of
// the list, with both bits set and both bodies' NumWitnesses up one.
CollisionBodyWitness *cbwitness_init(CollisionBodyWitness *w,
                                     CollisionBody *b1, CollisionBody *b2);

// 0x001cba18. Ends any collision, comes off the list, and clears what the
// constructor set. A track polygon's body left with no witness is
// destroyed here, through its table. The slot back to the pool when
// flags & 1.
void cbwitness_destroy(CollisionBodyWitness *w, int32_t flags);

// 0x001cea40, operator delete.
void cbwitness_delete(void *p);

// 0x001cbea8. The collision destroyed, the counts down one -- the bodies'
// NumCollisions and the stats' whether or not there was one.
void cbwitness_end_collision(CollisionBodyWitness *w);

// 0x001cbf18. 0 while there is a collision; 1 when the boxes no longer
// touch, or neither body looks actively, or either has collisions off.
int32_t cbwitness_has_expired(CollisionBodyWitness *w);

// 0x001cc010. Whether hitting b stirs the yaw control: a car or a
// smokeable does, a track polygon when it is a wall.
int32_t is_yaw_control_inducing_collision_body(const CollisionBody *b);

// 0x001cc248. Destroys every witness.
void cbwitness_eliminate_all(void);

// 0x001cc290. Empty.
void cbwitness_debug_print(CollisionBodyWitness *w);

// 0x001cc298. The pair's bit, as the byte masked -- not 0 or 1. 0 when
// either body has no number.
int32_t cbwitness_does_witness_exist(const CollisionBody *a,
                                     const CollisionBody *b);

// ------------------------------------------------------- CarCollisionBody
//
// carcollisionbody.c. A car's body: the car's own position, velocity and
// rotation while it drives on rails, its RigidBody's in physics mode; its
// volume the car's `<model>_CV` from the disc, or a box when there is none;
// and an impulse on it is damage, a rumble, a flinch from the driver and a
// jolt in the force feedback. Car's constructor makes one from the pool.

// gp-23156 and gp-16016, 0x0032317c and 0x00324d60. The AI's tuning
// switches: nothing on the disc writes either, and while one is set no car
// collides. They are here until the AI (task 26), which reads them too.
extern int32_t BoringAIForCameraTuningOn;
extern int32_t WilliamsAITuningMode;

// What an impulse reaches through a seam. The damage, the pursuit and the
// driver's animation change what happens next, so a NULL seam that is
// reached aborts, as car.h's AnimatedDriver seams do; main.c binds the
// damage to cardamage.c (task 51), and nothing sets pAnimatedDriver yet.
// The rumble and the force feedback are only felt, so a NULL one is
// skipped.
//
//   CarDamage::AddDamage           0x001aba30  BodyDamage, the markers, the
//                                              glass, the effects, and
//                                              ApplyDamage: cardamage.c
//   tCopManager::MonitorImpact     0x00213ff0  the pursuit: copmgr.c's
//                                              copmgr_car_impact
//   AnimatedDriver::BeginCollision 0x0019fa20  the render path (task 29)
//   PortRumbleImpact               0x00152fa0  PortRumble, a small envelope
//   Car::StartForceImpact          0x00133160  PortPlayCrash
//
// StartForceImpact takes its vector by value; the seam's is a copy the
// callee may change.
struct AnimatedDriver;
struct Car;
struct CarDamage;
struct tCopManager;

typedef void (*CarDamageAddDamageFn)(struct CarDamage *d, const bVector3 *at,
                                     float amount);
// The demo calls MonitorImpact(car, amount) whenever there is a cop
// manager. Retail (0x001d84bc) only calls it for an amount of 1 or more,
// with a third word: whether one of the body's collisions is two cars'.
// The seam takes the body so that copmgr.c can do both; this file keeps
// the demo's test of the manager, which is retail's too.
struct CarCollisionBody;
typedef void (*CopManagerMonitorImpactFn)(struct tCopManager *m,
                                          struct CarCollisionBody *b,
                                          float amount);
typedef void (*AnimatedDriverBeginCollisionFn)(struct AnimatedDriver *d,
                                               int32_t type,
                                               int32_t priority);
typedef void (*PortRumbleImpactFn)(int32_t port, float amount);
typedef void (*CarStartForceImpactFn)(struct Car *c, bVector3 *dir,
                                      float amount);
extern CarDamageAddDamageFn           gCarDamageAddDamageFn;
extern CopManagerMonitorImpactFn      gCopManagerMonitorImpactFn;
extern AnimatedDriverBeginCollisionFn gAnimatedDriverBeginCollisionFn;
extern PortRumbleImpactFn             gPortRumbleImpactFn;
extern CarStartForceImpactFn          gCarStartForceImpactFn;

// DriverAnimationType (.mdebug t1376), the five BeginCollision is asked for.
#define DRIVER_ANIMATION_TYPE_COLLISION_LIGHT 6
#define DRIVER_ANIMATION_TYPE_COLLISION_FRONT 7
#define DRIVER_ANIMATION_TYPE_COLLISION_RIGHT 8
#define DRIVER_ANIMATION_TYPE_COLLISION_LEFT  9
#define DRIVER_ANIMATION_TYPE_COLLISION_BACK  10

// 0x001cd750. Dynamic's constructor with the next ID, CAR_COLLISION_BODY and
// the car's TopologyCoordinate; the table, the count up, pCar, active
// detection on, both stamps WorldTimer, and "Car<driver>" for a name. The
// volume is the pipeline one named `<BaseModelName>_CV`, moved to the car
// type's centre of gravity, or a new RectPolyhedron 4.382 long, 1.942 wide
// and 0.824 high when the disc has none. Then the volumes and the box.
CarCollisionBody *carcollisionbody_init(CarCollisionBody *b, struct Car *car);

// 0x001cd898, slot 8. The count down; the volume destroyed when the disc
// has no `_CV` for the car -- which is the box the constructor made, or a
// pipeline volume unloaded since; then Dynamic's destructor, and the slot
// back to the pool when flags & 1.
void carcollisionbody_destroy(CarCollisionBody *b, int32_t flags);

// 0x001ce800 and 0x001ce7f0, operator new and delete: the pool.
void *carcollisionbody_new(void);
void  carcollisionbody_delete(void *p);

// 0x001ce7d0, 0x001ce7b0, 0x001ce790, slots 24, 32 and 40: the RigidBody's
// position, velocity and rotation in physics mode, the car's otherwise.
bVector3 *carcollisionbody_get_position(CollisionBody *b);
bVector3 *carcollisionbody_get_velocity(CollisionBody *b);
bMatrix4 *carcollisionbody_get_rotation(CollisionBody *b);

// 0x001cdad0, slot 64. BeginMove, then Car::Move. A step the car does not
// finish -- Move answers the time it took, and less than t is a car that
// hit something on rails -- goes to physics mode through slot 112 with no
// other body, and the rest of it is moved again. Then UpdatePosition.
void carcollisionbody_move(CollisionBody *b, float t);

// 0x001ce780, 0x001ce718, 0x001ce778, 0x001ce708, 0x001ce6f8: 1.0,
// TERRAIN_TYPE_CAR, 1, 0.1 and 0.3.
float   carcollisionbody_consider_impulse(CollisionBody *b, bVector3 *j,
                                          bVector3 *at);
int32_t carcollisionbody_get_terrain_type(CollisionBody *b);
int32_t carcollisionbody_is_moveable(CollisionBody *b);
float   carcollisionbody_get_bounciness(CollisionBody *b);
float   carcollisionbody_get_friction(CollisionBody *b);

// 0x001cdbe8, slot 128. The impulse scaled down to what a car of mass 1.3
// would take when the car is lighter, all four lanes; into the RigidBody
// with the angular part at 0.4; then AddDamage and AnimateCollisionReaction
// with its length.
void carcollisionbody_apply_impulse(CollisionBody *b, bVector3 *j,
                                    bVector3 *at);

// 0x001cdca0. `at` into the car's frame (the transpose of the RigidBody's
// rotation, as a point) and 0.03 of the size to CarDamage::AddDamage when
// the car has damage; a rumble on the player's port when the car is a
// player's and the race is not replaying (instant, auto or the replay
// demo), past the race, or in either demo; and the size to the cop manager.
void carcollisionbody_add_damage(CarCollisionBody *b, bVector3 *at,
                                 float amount);

// 0x001cddc0. With a driver to animate: past 20, the impulse in the car's
// frame picks the flinch by the larger of x and y and that one's sign
// (+x back, -x front, +y left, -y right) at priority 3; past 4, the light
// one at 2. Past 4 on a player's car, the force feedback's jolt too.
void carcollisionbody_animate_collision_reaction(CarCollisionBody *b,
                                                 bVector3 *j, float amount);

// 0x001cdb50, slot 136. 0 while either AI switch is set; then
// CollisionsDisabled == 0.
int32_t carcollisionbody_are_collisions_enabled(CollisionBody *b);

// 0x001cdb78, slot 152. The RigidBody's, but never more than 1 / 1.3.
float carcollisionbody_get_mass_inverse(CollisionBody *b);

// 0x001cdba0, slot 160. The RigidBody's with its first three rows at 0.4,
// all four lanes, into ScaledInverseInertiaTensor; the fourth row as it is.
bMatrix4 *carcollisionbody_get_inertia_tensor_inverse(CollisionBody *b);

// 0x001ce720, slot 184. Car::IsBlinking, or Car::IsPoofed when it is not.
int32_t carcollisionbody_is_blinking(CollisionBody *b);

// Inline in the image, and out of line at 0x001ce6c0 .. 0x001ce6f0.
static inline void carcollisionbody_set_last_yaw_control_collision_time(
    CarCollisionBody *b, const Timer *t)
{
    b->LastYawControlCollisionTime = *t;
}

static inline void carcollisionbody_set_last_penetration_time(
    CarCollisionBody *b, const Timer *t)
{
    b->LastPenetrationTime = *t;
}

static inline Timer carcollisionbody_get_last_yaw_control_collision_time(
    const CarCollisionBody *b)
{
    return b->LastYawControlCollisionTime;
}

static inline Timer carcollisionbody_get_last_penetration_time(
    const CarCollisionBody *b)
{
    return b->LastPenetrationTime;
}

static inline struct Car *carcollisionbody_get_car(const CarCollisionBody *b)
{
    return b->pCar;
}

// Retail's 0x001d8058, slot 16: a section for the body named
// "CarCollisionBody" around Dynamic's; the car's driver number
// checksummed; on a restore the physics pointers again, and taking or
// restoring the box from where the body is; the box checksummed and the
// three Timers moved.
void carcollisionbody_do_snapshot(CollisionBody *b, struct ReplaySnapshot *s);

// 0x001cda20. Clears pSystem and pBody. Then, if PhysicsMode is set and the
// car moves by PHYSICS_MOVEMENT or MELLOW_MOVEMENT, points them at the
// mover's PhysicsSystem base (mover + 8) and its RigidBody (mover + 24).
// The image's movz guards a NULL mover in the first store and then reads
// through it in the second; SetMovementMode never leaves one, and the port
// aborts on it.
void carcollisionbody_setup_physics_pointers(CarCollisionBody *b);

// 0x001cda80, slot 112 of _vt$16CarCollisionBody. The car on the other
// side -- `other`'s pCar if it is a car's body, Type 0 (`lb` at 12), NULL
// otherwise or with no `other` -- goes to Car::SetToPhysicsMode, and the
// pointers are set up again after it.
void carcollisionbody_set_to_physics_mode(CarCollisionBody *b,
                                          CollisionBody *other);

// 0x001cd068. Static, and a stub on the disc: `sw zero,0(a0); jr ra;
// lwc1 $f0,0(a0)`. The distance is 0 and the speed stored through `speed`
// is 0; neither body is read. Car::GetDistanceAndSpeed is its caller.
float dynamiccollisionbody_get_distance_and_speed(float *speed,
                                                  DynamicCollisionBody *a,
                                                  DynamicCollisionBody *b);

// --------------------------------------------------------------- Contact
//
// contact.c. World::DoTimestepCollisions (0x0014b110) asks every witness
// for a contact, resolves them in the list's order, and takes a resolved
// body's other contacts off the list.

// 0x003243d4. Made by InitContact: 32 slots, and it grows.
extern BSlotPool *ContactSlotPool;

// 0x003243d8 .. 0x003243f8, the tuning the image reads. Nothing writes
// them. Beside them on the disc are ContactDebug (0), Restitution (0.1),
// TestImpulse (1.0) and ContactFrictionCoefficient (0.3), which nothing
// reads; CollisionImpulse's 0.3 and 0.1 are literals of their own.
extern float ContactThreshold;              // 0.05
extern float WaferBias;                     // 0.5
extern float MinimumContactImpulseFactor;   // 0.3
extern float MinimumContactImpulseSpeed;    // 0.1
extern float MaxFrictionScrapeSpeed;        // 1.0

// Collision.obj's `new Collision(w, pt)` -- bOMalloc on CollisionSlotPool,
// then the constructor (0x0020b290) -- which BeginCollision makes, and
// Collision::AddImpulse (0x0020b450), which CollisionImpulse calls with the
// contact point, the impulse on the second body and the sliding speed.
// collision.c has both, and main.c points these at them; they stay
// pointers so the checkers that link contact.c need not link collision.c.
// A collision is state the sound and the damage read, so a NULL seam that
// is reached aborts.
extern struct Collision *(*gCollisionNewFn)(CollisionBodyWitness *w,
                                            bVector3 *pt);
extern void (*gCollisionAddImpulseFn)(struct Collision *c, bVector3 *at,
                                      bVector3 *impulse, float scrape);
// The witness's DoSnapshot reaches the Collision's through this one.
struct ReplaySnapshot;
extern void (*gCollisionDoSnapshotFn)(struct Collision *c,
                                      struct ReplaySnapshot *s);

// 0x001ca170 and 0x001ca1a0. EndGameFlowLoadingTrackSpecific and
// BeginGameFlowUnloadingTrackSpecific are the callers.
void init_contact(void);
void close_contact(void);

// 0x001ca1c8, static. Every contact with b on it off the list and freed.
void contact_remove_contacts(ContactNode *list, CollisionBody *b);

// 0x001ca240, static. The list's order: 0 -- a goes first -- when a backs
// up further than b.
int32_t contact_time_sorting(const Contact *a, const Contact *b);

// 0x001ca268. The three pointers, BackupTime from FindContactTime, and the
// loop it was found in.
Contact *contact_init(Contact *c, CollisionBody *b1, CollisionBody *b2,
                      CollisionBodyWitness *w);

// 0x0014c188 and 0x0014c330, inline in the image: the slot back to the
// pool when flags & 1.
void contact_destroy(Contact *c, int32_t flags);
void contact_delete(void *p);

// 0x001ca2a8. Eight halvings of [0, the shorter of the two bodies'
// GetMaxBackupTime]: back to where VClip sees them overlap, forward to
// where it does not. Parted by less than ContactThreshold is close enough,
// and that time is the answer. Still overlapping after the eighth, the
// bodies are crowbarred apart there. CrowbarVector is zeroed first.
float contact_find_contact_time(Contact *c);

// 0x001ca460. The normal of t's wafer, facing d: the face's plane normal,
// turned round unless d's position is more than WaferBias below the plane
// -- that is, above it less the bias. The fourth lane is 0.
void find_wafer_normal(bVector3 *out, TrackPolygonCollisionBody *t,
                       DynamicCollisionBody *d);

// 0x001ca538. Both bodies at t; a direction to push them -- the wafer's
// normal when either is a track polygon (away from the second body), the
// line between the centres otherwise -- and up to twenty steps of 0.05
// along it, the first body moved back and the second on (each only if it
// is moveable), until VClip no longer sees them overlap. That push is
// CrowbarVector; twenty steps that do not part them leave it as it was.
void contact_crowbar(Contact *c, float t);

// 0x001ca760. Both bodies to physics mode against each other, backed up
// BackupTime, parted by CrowbarVector and recomputed; the impulse; then
// recomputed again and moved on through BackupTime.
void contact_resolve(Contact *c);

// 0x001ca968. The midpoint of the witness's two closest points in the
// world, and the normal from the first body to the second: a static
// body's wafer normal, or the line between the closest points, or between
// the centres when those coincide.
void contact_find_contact_point_and_normal(Contact *c, bVector3 *point,
                                           bVector3 *normal);

// 0x001cabb0. No callers. `point` moved onto the plane through both
// centres that is square to up's part across the line between them: for
// two level bodies, the horizontal plane through their centres.
void contact_find_planar_collision_contact_point(Contact *c,
                                                 bVector3 *point);

// 0x001cad30 and 0x001cad60, static. v + w x r, all four lanes; and
// n . ((M (a x n)) x a), the rotational part of the impulse's denominator.
void  get_contact_point_velocity(bVector3 *out, bVector3 *v, bVector3 *w,
                                 bVector3 *r);
float denominator_term(bMatrix4 *m, bVector3 *a, bVector3 *n);

// 0x001cade0. Rounds of impulse at the contact point until the bodies stop
// closing: the restitution's impulse along the normal, with a floor; as
// much of it as each body will take (ConsiderImpulse's answer, -57575
// for none at all); friction against the slide; and a car scraping
// something immovable past 30 pulled back. Each round goes to both bodies
// and the Collision. A round both bodies take whole, or one that a body
// answers negative for, is the last.
void contact_collision_impulse(Contact *c);

// 0x001cbde0. The witness's collision, begun at pt if there is none.
struct Collision *cbwitness_get_collision(CollisionBodyWitness *w,
                                          bVector3 *pt);

// 0x001cbe18. Both bodies' NumCollisions and the stats up one, and a new
// Collision.
void cbwitness_begin_collision(CollisionBodyWitness *w, bVector3 *pt);

// Retail's 0x001d6168: a section for the witness named
// "CollisionBodyWitness" around VCWitness's, then a byte for whether it
// has a Collision; if so a restore begins one (at no point) and the
// Collision's own snapshot follows.
void cbwitness_do_snapshot(CollisionBodyWitness *w, struct ReplaySnapshot *s);

// 0x001cc058. VClip on the two bodies where they are now; PrintThisTime
// cleared. Overlapping: two dynamic bodies one of which blinks only stamp
// a car's LastPenetrationTime; otherwise a car hit by something that stirs
// the yaw control is stamped, and a new Contact joins `list` in order.
void cbwitness_test_for_contact(CollisionBodyWitness *w, ContactNode *list);

#endif
