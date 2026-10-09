// smokeable -- the head of Smokeable, and the two calls World makes into
// Smokeable.obj before it is ported.
//
// A smokeable is a breakable roadside object: a sign, a fence, a bin. It
// starts as a virgin smokeable, a body with no record of its own (ID
// ~index), and becomes a Smokeable when a car first comes close
// (ConvertToSmokeable, collisionbody.h's seam). The stab is
//
//   Smokeable:Tt2113=s992!2,020,2000;022048,757
//
// so two bases: DynamicCollisionBody at 0, and a PhysicsSystem at 256.
// World::DoTimestepCollisions reads one field, BreakingStrength.
// ConsiderImpulse (0x0020d540) stores -1 there when an impulse breaks the
// smokeable. This names the record
// up to pSmokeableSpawner and stops, like player.h. The rest --
// TheTopologyCoordinate at 296, TheWorldObject at 864, the two emitter
// lists, the counts and Awake at 984 -- comes with Smokeable.obj.

#ifndef SMOKEABLE_H
#define SMOKEABLE_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "collisionbody.h"
#include "physicssystem.h"
#include "rigidbody.h"
#include "timer.h"

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
    float    Padding2;                      // 204
    bNode    DynamicEmitterList;            // 208
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

typedef struct Smokeable {
    DynamicCollisionBody Dynamic;               //   0
    PhysicsSystem        System;                // 256  the second base
    struct SmokeableInfo *SI;                   // 272
    float    AnchorStrength;                    // 276
    float    BreakingStrength;                  // 280  -1 once broken
    Timer    TimeCreated;                       // 284
    Timer    TimeAwoken;                        // 288
    struct SmokeableSpawner *pSmokeableSpawner; // 292
    // ... to 992.
} Smokeable;

typedef char smokeable_layout_check[
    (offsetof(Smokeable, System) == sizeof(DynamicCollisionBody)
     && (sizeof(void *) != 4
         || (offsetof(Smokeable, System) == 256
             && offsetof(Smokeable, SI) == 272
             && offsetof(Smokeable, BreakingStrength) == 280
             && offsetof(Smokeable, pSmokeableSpawner) == 292))) ? 1 : -1];

// Smokeable::Break (0x0020d8f8). The smokeable comes apart: it writes the
// dynamic bodies that should look for new witnesses into `pieces`, and
// returns how many it wrote. Not ported. DoTimestepCollisions reaches it
// only for a body whose BreakingStrength is -1, and nothing in the port
// makes a smokeable yet, so a NULL seam that is reached aborts.
extern int32_t (*gSmokeableBreakFn)(Smokeable *s,
                                    DynamicCollisionBody **pieces);

// DeleteFarAwaySmokeableCollisionBodies (0x0020bc40). DoTimestepMove calls
// it once every 128 world steps. Not ported, and a NULL seam is skipped:
// with no smokeables there is nothing far away to delete.
extern void (*gDeleteFarAwaySmokeableCollisionBodiesFn)(void);

#endif
