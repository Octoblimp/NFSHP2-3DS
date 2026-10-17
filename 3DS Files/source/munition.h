// munition -- Munition.obj, retail 0x001be4b8 .. 0x001bfea0: what the
// helicopter drops and fires (12k-6).
//
// Every munition is a Smokeable with a word more, BackupDone, and comes
// from a pool of its own. Three kinds, one creator each, registered on
// SmokeableCreators by InitMunitions as the world is made:
//
//   Rocket        (ST_ROCKET, 1)          Munition -> Rocket
//   SmokeBomb     (ST_SMOKEBOMB, 2)       Munition -> DroppedBomb -> SmokeBomb
//   DroppedSpikes (ST_DROPPED_SPIKES, 3)  Munition -> DroppedBomb -> ...
//
// The helicopter's FireSalvo (chopperfire.c) builds them through their
// default constructors: a SmokeBomb or DroppedSpikes is the info
// "CS_SMOKEBOMB" with the model "SMOKEBOMB" (the spikes look like a smoke
// bomb), a Rocket "CS_Rocket" and "ROCKET". LaunchMunition gives one its
// place and speed, wakes it and lights its anchor emitters.
//
// A bomb falls as a smokeable does. A smoke bomb goes off when it touches
// a car or when its Lifetime runs out; spikes go off at the first impulse
// on them (the ground, mostly). A rocket flies itself: it turns toward its
// target car at 90 degrees a second, at 30 units a second, holding 0.9
// above the ground, and goes off when anything strikes it, its target is
// gone, or its Lifetime runs out.
//
// Going off is OnLifetimeEnd (slot 216): the class's explosion emitters
// copied into MunitionEffectsHandler at the munition's place, and
// ExplodeWarhead -- every car within the class's range pushed away and up,
// a car hit hard enough brought to an e-brake stop (and a player's given
// the slow-motion camera, for a smoke bomb). Spikes then lay a spike belt
// across the road where they landed.

#ifndef MUNITION_H
#define MUNITION_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bmatrix.h"
#include "bslotpool.h"
#include "smokeable.h"

struct Car;

// 1152 bytes: Smokeable (1136) and BackupDone. DroppedBomb and SmokeBomb
// add nothing.
typedef struct Munition {
    Smokeable Base;                 //    0
    int32_t   BackupDone;           // 1136  Backup ran this step
    uint8_t   _pad1140[12];         // 1140
} Munition;                         // 1152

typedef Munition DroppedBomb;
typedef Munition SmokeBomb;

// 1168 bytes.
typedef struct DroppedSpikes {
    Munition Base;                  //    0
    int32_t  DeploySpikes;          // 1152  struck: go off at the next Move
    uint8_t  _pad1156[12];          // 1156
} DroppedSpikes;                    // 1168

// 1168 bytes. The demo's had a RocketSound as well; retail has none.
typedef struct Rocket {
    Munition    Base;               //    0
    struct Car *Target;             // 1152  NULL once struck
    float       Yaw;                // 1156  degrees
    uint8_t     _pad1160[8];        // 1160
} Rocket;                           // 1168

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char munition_layout_check[
    (offsetof(Munition, BackupDone) == 1136
     && sizeof(Munition) == 1152
     && offsetof(DroppedSpikes, DeploySpikes) == 1152
     && sizeof(DroppedSpikes) == 1168
     && offsetof(Rocket, Target) == 1152
     && offsetof(Rocket, Yaw) == 1156
     && sizeof(Rocket) == 1168) ? 1 : -1];
#endif

// ExplodeParams, 28 bytes (.mdebug type#3907).
typedef struct ExplodeParams {
    float   MaxStrength;            //  0  the impulse within MinRange
    float   MinStrength;            //  4  ... at MaxRange
    float   ArmZAdjust;             //  8  the impulse's point, above the car
    float   CoordZAdjust;           // 12  more up, for a car on its wheels
    float   MinRange;               // 16
    float   MaxRange;               // 20
    int32_t bRequestZoneCamera;     // 24
} ExplodeParams;                    // 28

// MunitionsType (.mdebug t2156), ExplodeWarhead's.
typedef int32_t MunitionsType;
#define MT_SMOKE_BOMB  ((MunitionsType)0)
#define MT_BANG_FLASH  ((MunitionsType)1)
#define MT_SPIKE_BOMB  ((MunitionsType)2)

// 0x003143d8, 0x003143f8 and 0x00314418.
extern const ExplodeParams SmokeBombExplodeParams;
extern const ExplodeParams DroppedSpikesExplodeParams;
extern const ExplodeParams RocketExplodeParams;

// 8 bytes, a bPList<AcidEmitter>: the explosions still playing.
typedef struct MunitionEffectsHandler {
    bNode List;                     // 0
} MunitionEffectsHandler;

// The tables, main (the body's, at 80) and the PhysicsSystem's (at 268).
#define MUNITION_VTABLE              0x002b7120u
#define MUNITION_SYSTEM_VTABLE       0x002b7100u
#define DROPPEDBOMB_VTABLE           0x002b7020u
#define DROPPEDBOMB_SYSTEM_VTABLE    0x002b7000u
#define SMOKEBOMB_VTABLE             0x002b6f20u
#define SMOKEBOMB_SYSTEM_VTABLE      0x002b6f00u
#define DROPPEDSPIKES_VTABLE         0x002b6e20u
#define DROPPEDSPIKES_SYSTEM_VTABLE  0x002b6e00u
#define ROCKET_VTABLE                0x002b6d20u
#define ROCKET_SYSTEM_VTABLE         0x002b6d00u

// gp-18440, gp-18436, gp-18432: 3 rockets, 14 smoke bombs, 8 spikes.
extern BSlotPool *RocketSlotPool;
extern BSlotPool *SmokeBombSlotPool;
extern BSlotPool *DroppedSpikesSlotPool;

// gp-18424, gp-18416, gp-18408: each class's explosion, WorldEffects'
// auto emitters of group "ROCKETEXPLD" (rockets and spikes) or
// "SMOKEBOMBEXPLD", copied. bTList<AcidEmitter>s, self-linked from boot.
extern bNode RocketEmitters;
extern bNode SmokeBombEmitters;
extern bNode DroppedSpikesEmitters;

// gp-18384. Made by InitMunitions and deleted by CloseMunitions.
extern MunitionEffectsHandler *TheMunitionEffectsHandler;

// Installs the ten tables. The game calls it once at boot, after
// smokeable_install_vtables.
void munition_install_vtables(void);

// InitMunitions (0x001be638) and CloseMunitions (0x001be680): world.h's
// gInitMunitionsFn and gCloseMunitionsFn. Init makes the handler, then
// each class's pool, creator and emitters (SmokeBomb, Rocket,
// DroppedSpikes); Close undoes them in that order and deletes the handler.
void init_munitions(void);
void close_munitions(void);

// The creators, 0x001be4b8 (Rocket), 0x001be538 (SmokeBomb) and
// 0x001be5b8 (DroppedSpikes): one from the class's pool, never NULL.
Smokeable *rocket_smokeable_creator(int32_t id, SmokeableInfo *info,
                                    uint32_t name_hash);
Smokeable *smokebomb_smokeable_creator(int32_t id, SmokeableInfo *info,
                                       uint32_t name_hash);
Smokeable *droppedspikes_smokeable_creator(int32_t id, SmokeableInfo *info,
                                           uint32_t name_hash);

// ---------------------------------------------------------- Munition

// 0x001be6c8 and 0x001be710.
Munition *munition_init(Munition *m, int32_t id, SmokeableInfo *info,
                        uint32_t name_hash);
void munition_destroy(Munition *m, int32_t flags);

// ExplodeWarhead(ExplodeParams *, MunitionsType), 0x001be778.
void munition_explode_warhead(Munition *m, const ExplodeParams *p,
                              MunitionsType type);

// LaunchMunition(bMatrix4 *, bVector3 *), 0x001bea40: placed at `m`
// moving at `v`, awake, the anchor emitters on.
void munition_launch(Munition *m, const bMatrix4 *mat, const bVector3 *v);

// GetFlatMatrix(bMatrix4 *), 0x001bea70: the identity at the position.
void munition_get_flat_matrix(Munition *m, bMatrix4 *out);

// Backup(float), slot 72, 0x001bead0: BackupDone, then the body's.
void munition_backup(CollisionBody *b, float t);

// ------------------------------------------------------- DroppedBomb

// 0x001beae0, 0x001beb20 and Move (0x001beb88, Smokeable::Move's).
Munition *droppedbomb_init(Munition *m, int32_t id, SmokeableInfo *info,
                           uint32_t name_hash);
void droppedbomb_destroy(Munition *m, int32_t flags);
void droppedbomb_move(CollisionBody *b, float dt);

// LaunchBomb, 0x001bfe90: LaunchMunition.
void droppedbomb_launch(Munition *m, const bMatrix4 *mat, const bVector3 *v);

// --------------------------------------------------------- SmokeBomb

// The default constructor (0x001beb90), from a slot of SmokeBombSlotPool,
// and the destructor (0x001bec28).
SmokeBomb *smokebomb_new(SmokeBomb *b);
void smokebomb_destroy(SmokeBomb *b, int32_t flags);

void smokebomb_on_lifetime_end(CollisionBody *b);     // 0x001bed20
void smokebomb_move(CollisionBody *b, float dt);      // 0x001bed78
int32_t smokebomb_get_smoke_type(CollisionBody *b);   // 0x001bfe10

// ----------------------------------------------------- DroppedSpikes

DroppedSpikes *droppedspikes_new(DroppedSpikes *s);   // 0x001bee88
void droppedspikes_destroy(DroppedSpikes *s, int32_t flags); // 0x001bef20

void droppedspikes_on_lifetime_end(CollisionBody *b); // 0x001bf078
void droppedspikes_move(CollisionBody *b, float dt);  // 0x001bf0d8
float droppedspikes_consider_impulse(CollisionBody *b, bVector3 *j,
                                     bVector3 *at);   // 0x001bf160
void droppedspikes_apply_impulse(CollisionBody *b, bVector3 *j,
                                 bVector3 *at);       // 0x001bf178
int32_t droppedspikes_get_smoke_type(CollisionBody *b); // 0x001bfd90

// DroppedSpikes::DoSnapshot, 0x001bef90, slot 16 (copsnap.c): a section
// "DroppedSpikes" with the object, DeploySpikes in a bool, then
// Smokeable's.
void droppedspikes_do_snapshot(CollisionBody *b, struct ReplaySnapshot *s);

// MakeSpikeBelt, 0x001bf188: on the ground (within 1 of it) and on a
// racing route's road, a strip four wide across the route, cut short
// where the road's edge is nearer than 2.
void droppedspikes_make_spike_belt(DroppedSpikes *s);

// ------------------------------------------------------------ Rocket

Rocket *rocket_new(Rocket *r);                        // 0x001bf340
void rocket_destroy(Rocket *r, int32_t flags);        // 0x001bf3d8

void rocket_on_lifetime_end(CollisionBody *b);        // 0x001bf4d0

// LaunchRocket(bMatrix4 *, bVector3 *, Car *), 0x001bf528: launched, its
// yaw along `v`, after `target`.
void rocket_launch(Rocket *r, const bMatrix4 *mat, const bVector3 *v,
                   struct Car *target);

void rocket_move(CollisionBody *b, float dt);         // 0x001bf598
float rocket_consider_impulse(CollisionBody *b, bVector3 *j,
                              bVector3 *at);          // 0x001bf8f8
void rocket_apply_impulse(CollisionBody *b, bVector3 *j,
                          bVector3 *at);              // 0x001bf908
int32_t rocket_get_smoke_type(CollisionBody *b);      // 0x001bfd10

// Rocket::DoSnapshot, 0x001bf910, slot 16 (copsnap.c): a section "Rocket"
// with the object, the yaw, the target through World's car pointer, then
// Smokeable's.
void rocket_do_snapshot(CollisionBody *b, struct ReplaySnapshot *s);

// --------------------------------------------- MunitionEffectsHandler

// The destructor (0x001bf980): every emitter off WorldEffects and
// deleted; with bit 0 of `flags` the handler freed.
void munitioneffectshandler_destroy(MunitionEffectsHandler *h,
                                    int32_t flags);

// DoTimestep(float), 0x001bfa38: each emitter that has finished (State
// not ACID_ON) off WorldEffects and deleted.
void munitioneffectshandler_do_timestep(MunitionEffectsHandler *h,
                                        float dt);

// AddEffect(bTList<AcidEmitter> *, bMatrix4 *), 0x001bfad0: a copy of
// each of `list`'s emitters, on, at `m`, added to WorldEffects and to the
// head of the handler's list.
void munitioneffectshandler_add_effect(MunitionEffectsHandler *h,
                                       bNode *list, const bMatrix4 *m);

// chopper.h's gMunitionEffectsDoTimestepFn: DoTimestep on
// TheMunitionEffectsHandler. Retail's Fly calls it unguarded; with no
// handler (no world) the port's does nothing.
void munition_effects_do_timestep(float dt);

#endif
