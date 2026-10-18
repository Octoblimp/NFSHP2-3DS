// terraineffect -- retail's TerrainEffectEmitters (0x00222248 ..
// 0x00222594; the demo's InitTerrainEffectEmitters is 0x0020e448): the
// particles the ground makes under a car's wheels and where something
// hits it, by its terrain (TASKS 60).
//
// Each terrain names an emitter group for each of seven effects
// (terraintype.h): DriveOver, DriveOver2, SkidSmoke, TireSpew, BottomOut,
// CollisionImpact and CollisionScrape. The object is a list of emitters
// for each effect and terrain, copies of WorldEffects' auto emitters of
// that group, made once when the world is built. Car::TriggerEffect
// (cartriggereffect.h) takes car effects 1 to 5 from lists 0 to 4, and a
// Collision (collision.c) triggers 5 and 6.
//
// Written up in docs/formats/car-effects.md.

#ifndef TERRAINEFFECT_H
#define TERRAINEFFECT_H

#include <stdint.h>

#include "blist.h"
#include "bvector.h"
#include "terraintype.h"

#define TERRAIN_EFFECT_DRIVE_OVER        0
#define TERRAIN_EFFECT_DRIVE_OVER2       1
#define TERRAIN_EFFECT_SKID_SMOKE        2
#define TERRAIN_EFFECT_TIRE_SPEW         3
#define TERRAIN_EFFECT_BOTTOM_OUT        4
// TERRAIN_EFFECT_COLLISION_IMPACT (5) and _SCRAPE (6) are collision.h's.
#define NUM_TERRAIN_EFFECTS              7

// 1848 bytes on the PS2: a bTList<AcidEmitter> for each effect and
// terrain, effect-major, `bMalloc(1848, "TerrainEffectEmitters", 0, 16)`.
typedef struct TerrainEffectEmitters {
    bNode Lists[NUM_TERRAIN_EFFECTS][NUM_TERRAIN_TYPES];
} TerrainEffectEmitters;

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char terraineffect_size_check[
    sizeof(TerrainEffectEmitters) == 1848 ? 1 : -1];
#endif

// The constructor (0x00222248): every list empty, then for each terrain
// in turn, each effect whose group name is not empty gets afxGetEmitters'
// copies of the group, by the name's bStringHash.
TerrainEffectEmitters *terrain_effect_emitters_construct(
    TerrainEffectEmitters *t);

// The deleting destructor (0x002223b0): from the last list to the first,
// each emitter off the list from its head and deleted with 3, as
// ~bTList<AcidEmitter> (0x00124bf0) does; then with bit 0 of `flags`,
// the object freed. NULL does nothing.
void terrain_effect_emitters_destroy(TerrainEffectEmitters *t,
                                     int32_t flags);

// TriggerEffect (0x00222438): each emitter of the effect's list for the
// terrain placed at `at` with no turn, given `velocity`'s three lanes to
// inherit and 0 in the fourth, and fired on WorldEffects for a burst of
// `scale` seconds (TriggerEmitter's negative step) with no car. The list
// is found with no bounds test, as the listing does.
void terrain_effect_emitters_trigger(TerrainEffectEmitters *t,
                                     int32_t effect, int32_t terrain,
                                     float scale, const bVector3 *at,
                                     const bVector3 *velocity);

// InitTerrainEffectEmitters (0x00222530): unless pTerrainEffectEmitters
// (gp-15816) is set, a new object there. CloseTerrainEffectEmitters
// (0x00222570): the object deleted and the pointer cleared. World's
// constructor and destructor call them (worldinit.c's seams).
void init_terrain_effect_emitters(void);
void close_terrain_effect_emitters(void);

#endif
