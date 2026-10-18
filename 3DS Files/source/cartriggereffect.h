// cartriggereffect -- retail's Car::TriggerEffect (0x0011e2b8, 720 bytes;
// the demo's is 0x0011e328): a burst of a car's particles (TASKS 60).
//
// Car.obj does not hold it; it sits with the effect system's code, after
// the car's render info. It is car.h's gCarTriggerEffectFn, which
// cardamage.c calls for a broken part (the glass of a light, a window or
// a mirror, the radiator's steam, the engine's smoke) at 0.1, 0.4 or 1
// for the part's level, careffects.c for the ground under the wheels
// each frame, and carrace.c for a tire that blows.
//
// Written up in docs/formats/car-effects.md; cross-check
// tools/cartriggereffect_check.py.

#ifndef CARTRIGGEREFFECT_H
#define CARTRIGGEREFFECT_H

#include <stdint.h>

#include "bvector.h"
#include "car.h"

// Nothing for a car with no render info, a scale of 0, CARFX_NONE, or a
// car whose rendering position is overridden (any view bit set).
//
// The emitters are the car's own list for the effect, its render info's
// EmitterList[effect], except for effects 1 to 5 (the ground's) while
// pTerrainEffectEmitters is set: those come from its list for effect - 1
// and the terrain in the low 16 bits of `where`.
//
// A wheel's effects (SKID_SMOKE, TIRE_SPEW, BLOWN_TIRE and
// DRIVE_ON_FLAT_TIRE) name the wheel's emitter position in the high 16
// bits of `where`, read signed; every other effect's wheel is 0. A wheel
// of 1 to 8 is placed from the car's Position, any other from its
// GeometryPosition, turned by its BodyMatrix. The emitters inherit `vel`,
// or the car's Velocity when it is NULL. (car.h names it `pos`.)
//
// Each emitter is fired on WorldEffects, for a burst of `scale` seconds
// (TriggerEmitter's negative step), once at each place of its position
// list: the wheel's, or for wheel 0 the one its data names
// (CarPosition). For each, the place goes into the fourth row of a copy
// of the emitter's LocalWorld, and that times the car's matrix becomes
// the LocalWorld. The copy goes back after the last place, keeping that
// place in its fourth row, as the listing's does.
void car_trigger_effect(Car *c, CarEffect effect, float scale,
                        int32_t where, bVector3 *vel);

#endif
