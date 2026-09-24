// collisionbody -- CollisionBody, DynamicCollisionBody and CarCollisionBody:
// the layouts, and the two methods Car's mode switches reach.
//
// All three belong to task 27 (track collision). Car holds a
// CarCollisionBody pointer at offset 52 and touches it four ways:
// IsCollideable dispatches through its vtable, GetCarSpaceBoundingBox and
// GetLastPenetrationTime read two of its fields, and SetMovementMode writes
// PhysicsMode at 84 -- 1 for the two movers that do real physics, 0 for the
// other five. So the records are stated here in full, the way topology.h
// states TopologyCoordinate: every field from the stabs, spelled out,
// because seven of them are pointers and a blob would be the right size on
// ARM only.
//
//   CollisionBody:Tt4605=s84!1,020,4596         base bTNode<CollisionBody>
//   DynamicCollisionBody:Tt4732=s256!1,020,4605 base CollisionBody
//   CarCollisionBody:Tt2951=s336!1,020,4732     base DynamicCollisionBody
//
// The vptr is CollisionBody's, at 80 (`$vf4605:148,640`).
//
// Two widths the stabs give but not their signs -- Type, Dynamic and the
// four counters are 8 bits, ID is 16 -- so they are unsigned here. Only
// Type is read, and only against zero.
//
// Task 27 should replace this notice when it ports the classes.

#ifndef COLLISIONBODY_H
#define COLLISIONBODY_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"

typedef struct CollisionBodyNode {
    struct CollisionBody *next;   // 0
    struct CollisionBody *prev;   // 4
} CollisionBodyNode;              // 8

typedef struct CollisionBody {
    CollisionBodyNode Link;                     //  0  bTNode<CollisionBody>
    struct ePoly *pPoly;                        //  8
    uint8_t   Type;                             // 12
    uint8_t   Dynamic;                          // 13
    uint16_t  ID;                               // 14
    uint8_t   NumWitnesses;                     // 16
    uint8_t   CollisionsDisabled;               // 17
    uint8_t   NumCollisions;                    // 18
    uint8_t   ActiveCollisionDetection;         // 19
    bVector2  BBoxMin;                          // 20
    bVector2  BBoxMax;                          // 28
    char      DebugName[40];                    // 36
    void     *pCaffeineObj;                     // 76
    uint32_t  _vtable;                          // 80
} CollisionBody;                                // 84

typedef struct DynamicCollisionBody {
    CollisionBody Body;                         //   0
    int32_t   PhysicsMode;                      //  84
    struct TrackPolygon *pTC;                   //  88
    void     *pSystem;                          //  92
    void     *pBody;                            //  96
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

// Timer is one word, `PackedTime` (`Timer:Tt2847=s4PackedTime:/030,0,32`,
// type 30 being uint32 in that unit). What the packing means is task 27's;
// Car only hands the word back. It is here rather than in a header of its
// own only because CarCollisionBody is its first holder -- the class that
// ports Timer's methods takes it.
typedef struct Timer {
    uint32_t PackedTime;                        //   0
} Timer;                                        //   4

typedef struct CarCollisionBody {
    DynamicCollisionBody Dynamic;               //   0
    struct Car *pCar;                           // 256
    Timer     LastPenetrationTime;              // 260
    Timer     LastYawControlCollisionTime;      // 264
    uint8_t   _pad268[4];                       // 268  the quadword round-up
    bMatrix4  ScaledInverseInertiaTensor;       // 272
} CarCollisionBody;                             // 336

// DynamicCollisionBody is 256 + 9 slacks, 292 on the host, and a pointer's
// alignment rounds it to 296: so pCar lands ten slacks on, and the pointer
// itself makes the eleventh.
typedef char carcollisionbody_layout_check[
    (CB_AT(CarCollisionBody, pCar, 256, 10)
     && CB_AT(CarCollisionBody, LastPenetrationTime, 260, 11)
     && CB_AT(CarCollisionBody, LastYawControlCollisionTime, 264, 11)
     && CB_AT(CarCollisionBody, ScaledInverseInertiaTensor, 272, 11)
     && sizeof(CarCollisionBody) == CB_ROUND(336 + 11 * CB_SLACK))
    ? 1 : -1];

// The vtables. Slot 136 is pure in CollisionBody and DynamicCollisionBody
// and is `AreCollisionsEnabled__16CarCollisionBody` (0x001cdb50) in the
// car's own, which is the table every Car's body actually carries: two
// global switches first, then `CollisionsDisabled == 0`, the byte read with
// `lb`. Car::IsCollideable is its one caller in Car.obj.
#define COLLISIONBODY_VTABLE        0x0029bf48u
#define DYNAMICCOLLISIONBODY_VTABLE 0x0029bcd8u
#define CARCOLLISIONBODY_VTABLE     0x0029bc08u

#define COLLISIONBODY_VT_SET_TO_PHYSICS_MODE    112
#define COLLISIONBODY_VT_ARE_COLLISIONS_ENABLED 136

// ------------------------------------------- the two methods Car needs
//
// collisionbody.c. Car's fourth slice brought them: SetMovementMode ends in
// the first, and the second is the only caller of Car::SetToPhysicsMode.
// Neither is in a table yet -- the tables are task 27's.

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

#endif
