// physcomp -- the physics component classes as objects: their vtables,
// their destructors, and the slot-pool operator new and delete each one
// declares. Also the ten pools themselves, and InitPhysics / ClosePhysics
// (PhysicsCar.obj, 0x00135068 and 0x001351b0), which make and delete them.
//
// RigidBody, Wheel, Suspension, Engine and DriveTrain each have a .c of
// their own, with the arithmetic and a checker that holds it to the image.
// Before PhysicsSystem nothing called any of them through a vptr, so none
// installed a table, and none had the destructor or the allocator: every
// harness built its objects in place and called the methods directly. This
// file adds the rest of each class without touching those five files or
// their checkers:
//
//   the tables      each class's _vt$, installed with vtable.c at the
//                   image's address. The slots are PhysicsComponent's.
//   the dtors       X::~X(this, flags), the chain down to
//                   ~PhysicsComponent and then, when flags & 1, operator
//                   delete. A PhysicsSystem destroys its components with
//                   flags 3 through slot 8, so this is what it reaches.
//   new / delete    bOMalloc and bFree on the class's pool. operator new
//                   ignores its size, since a pool has only one.
//
// The steering is here too, although it is not a PhysicsComponent: it has
// its own three-slot table, and PhysicsCar calls it through slot 8 and 16.
// Aerodynamics has no vtable and no destructor, but it is allocated from a
// pool of its own, so its delete is here as well.
//
// See docs/formats/physics-components.md.

#ifndef PHYSCOMP_H
#define PHYSCOMP_H

#include <stddef.h>
#include <stdint.h>

#include "aerodynamics.h"
#include "bslotpool.h"
#include "drivetrain.h"
#include "engine.h"
#include "physicssystem.h"
#include "rigidbody.h"
#include "steering.h"
#include "suspension.h"
#include "wheel.h"

// ------------------------------------------------------------- the pools

// PhysicsCar.obj's .sdata, gp-23408 .. gp-23372 (0x00323080 ..
// 0x003230a4), in this order. Zero until InitPhysics and again after
// ClosePhysics. The last belongs to a class the port does not have yet;
// its pool is made so the counts and names match the image's.
extern BSlotPool *RigidBodySlotPool;                // gp-23408
extern BSlotPool *TwoWheelAckermanSteeringSlotPool; // gp-23404
extern BSlotPool *WheelSlotPool;                    // gp-23400
extern BSlotPool *EngineSlotPool;                   // gp-23396
extern BSlotPool *DriveTrainSlotPool;               // gp-23392
extern BSlotPool *AerodynamicsSlotPool;             // gp-23388
extern BSlotPool *SuspensionSlotPool;               // gp-23384
extern BSlotPool *MellovatorSlotPool;               // gp-23380
extern BSlotPool *MellowMoverSlotPool;              // gp-23376
extern BSlotPool *NullMoverSlotPool;                // gp-23372

// 0x00135068. Ten bNewSlotPool calls, all in memory pool 16, where n is
// the number of drivers in the race:
//
//   RigidBody n + 32      Ackerman n        Wheel 4n       Engine n
//   DriveTrain n          Aerodynamics n    Suspension 4n
//   Mellovator n          MellowMover n     NullMover n
//
// The 32 spare bodies are for the other things that fly: Smokeable and the
// weapons build RigidBodies too. **The image takes n from
// TheRaceParameters.NumDriverInfo** (0x00312814, `lw s0,10260(v0)`) and has
// no argument. RaceParameters is task 26's, so until it is the port's
// caller passes the count.
//
// The slot sizes are sizeof() for all ten classes, which is the image's
// number on the 3DS -- the layout asserts in each header say so -- and
// wider on a 64-bit host. NullMover's is carmodes.h's.
void InitPhysics(int32_t numDriverInfo);

// 0x001351b0. bDeleteSlotPool on all ten in the same order, then all ten
// zeroed. The deletes come first: a pool is deleted with its pointer still
// set.
void ClosePhysics(void);

// ----------------------------------------------------- operator new/delete

// Each new is `lw a0,gp(pool) ; jal bOMalloc` -- the full path, which
// clears the slot, since InitPhysics leaves every pool's flags at the 15
// bNewSlotPool starts them with. Each delete is `j bFree` with the pool in
// the delay slot. None checks the pool pointer: a new before InitPhysics
// is a NULL pool.
//
//   RigidBody     0x00193f00 / 0x00193ef0
//   Wheel         0x0019b980 / 0x0019b970
//   Suspension    0x0019c380 / 0x0019c370
//   Engine        0x00183e38 / 0x00183e28
//   DriveTrain    0x00183ce8 / 0x00183cd8
//   Ackerman      0x0019c478 / 0x0019c468
//   Aerodynamics  inlined into PhysicsCar's ctor / 0x001374b8
RigidBody                *rigidbody_new(void);
Wheel                    *wheel_new(void);
Suspension               *suspension_new(void);
Engine                   *engine_new(void);
DriveTrain               *drivetrain_new(void);
TwoWheelAckermanSteering *ackerman_new(void);
Aerodynamics             *aerodynamics_new(void);

void rigidbody_delete(void *p);
void wheel_delete(void *p);
void suspension_delete(void *p);
void engine_delete(void *p);
void drivetrain_delete(void *p);
void ackerman_delete(void *p);
void aerodynamics_delete(void *p);

// ------------------------------------------------------- the destructors

// Each is the image's `_$_X(this, flags)`. What the chain stores:
//
//   ~RigidBody   0x00193fc0  ~PhysicsComponent(this, 0)
//   ~Wheel       0x0019b9e0  ~SkidMaker(this+384, 2), ~PhysicsComponent
//   ~Suspension  0x0019c418  ~PhysicsComponent
//   ~Engine      0x00182478  its own vptr, then ~PhysicsComponent
//   ~DriveTrain  0x00183dc0  ~PhysicsComponent
//   ~Ackerman    0x0019c4a0  its own vptr, then ~Steering(this, 0)
//   ~Steering    0x0019ba98  its own vptr, then __builtin_delete
//
// ~PhysicsComponent (0x00192438) stores the base's vptr and tail-calls
// ~bNode, which is empty, so **a destroyed component carries
// PHYSICSCOMPONENT_VTABLE** and a destroyed Ackerman carries
// STEERING_VTABLE. Engine and Ackerman store their own first, which only a
// virtual call from inside the chain could see; there is none.
//
// Then `andi s0,s0,1 ; beq` and a tail jump to the class's operator
// delete. Steering's is __builtin_delete instead, which is bFree on the
// general heap -- malloc's, in the port, as PhysicsSystem's is. No
// Steering is ever made except as an Ackerman's base, whose destructor
// passes 0.
void rigidbody_destroy(RigidBody *rb, int32_t flags);
void wheel_destroy(Wheel *w, int32_t flags);
void suspension_destroy(Suspension *s, int32_t flags);
void engine_destroy(Engine *e, int32_t flags);
void drivetrain_destroy(DriveTrain *d, int32_t flags);
void ackerman_destroy(TwoWheelAckermanSteering *a, int32_t flags);
void steering_destroy(Steering *s, int32_t flags);

// 0x0019ba40, ~SkidMaker(this, flags), which is MakeNoSkid (0x001a0c20)
// and then __builtin_delete when flags & 1. MakeNoSkid is
// `if (pSkidSet) SkidSet::FinishedAddingSkids(pSkidSet)` -- the trail is
// closed off, and pSkidSet is left as it was.
//
// SkidSet is task 27's. Nothing in the port sets pSkidSet yet -- only
// MakeSkid does, and it is not ported -- so the call goes through a seam
// that task 27 fills. A set pSkidSet with no seam installed aborts: it
// would mean a skid was started by code that does not exist.
extern void (*gSkidSetFinishedAddingFn)(void *skidSet);
void skidmaker_destroy(SkidMaker *sm, int32_t flags);

// ------------------------------------------------------------ the tables

// _vt$10Suspension and the rest, 72 bytes each: nine entries, the first
// empty, then PhysicsComponent's eight slots (physicssystem.h). Wheel,
// Suspension, Engine and DriveTrain do not override ResolveForces, so
// their slot 48 is the base's 0x00192c00; RigidBody's is its own. Every
// delta is zero -- the base is at offset 0 in each.
#define RIGIDBODY_VT_ENTRIES   9
#define WHEEL_VT_ENTRIES       9
#define SUSPENSION_VT_ENTRIES  9
#define ENGINE_VT_ENTRIES      9
#define DRIVETRAIN_VT_ENTRIES  9

// _vt$24TwoWheelAckermanSteering (0x00298ff8) and _vt$8Steering
// (0x00299018), 32 bytes: the destructor, SetSteering and DoSnapshot, the
// last two `__pure_virtual` in the base's.
#define STEERING_VT_ENTRIES      4
#define STEERING_VT_DTOR         8
#define STEERING_VT_SET_STEERING 16
#define STEERING_VT_DO_SNAPSHOT  24

typedef void (*SteeringDtorFn)(void *self, int32_t flags);
typedef void (*SteeringSetSteeringFn)(void *self, uint16_t bam);
typedef void (*SteeringDoSnapshotFn)(void *self, void *snap);

// The entries, by the image's own names, so a harness can say which one a
// slot holds. Each forwards to the port function the comment names; the
// types differ only in `this` and in what GetState and GetDerivative
// return. Engine's and DriveTrain's GetDerivative return an int in the
// port where the slot returns a float *; nothing reads the value --
// PhysicsSystem::GetDerivative discards it -- so the thunks return NULL.
//
// TwoWheelAckermanSteering::DoSnapshot (0x0019bac0) is not ported --
// ReplaySnapshot, as everywhere -- and its entry is NULL, so a call
// aborts in vt_slot rather than doing nothing.
void    vt_RigidBody_dtor(void *self, int32_t flags);
int32_t vt_RigidBody_GetSize(void *self);
float  *vt_RigidBody_GetState(void *self);
void    vt_RigidBody_GetState_Pf(void *self, float *a);
void    vt_RigidBody_SetState_Pf(void *self, float *a);
void    vt_RigidBody_ResolveForces(void *self);
float  *vt_RigidBody_GetDerivative_Pf(void *self, float *out);
void    vt_RigidBody_ComputeAuxiliaries(void *self);

void    vt_Wheel_dtor(void *self, int32_t flags);
int32_t vt_Wheel_GetSize(void *self);
float  *vt_Wheel_GetState(void *self);
void    vt_Wheel_GetState_Pf(void *self, float *a);
void    vt_Wheel_SetState_Pf(void *self, float *a);
float  *vt_Wheel_GetDerivative_Pf(void *self, float *out);
void    vt_Wheel_ComputeAuxiliaries(void *self);

void    vt_Suspension_dtor(void *self, int32_t flags);
int32_t vt_Suspension_GetSize(void *self);
float  *vt_Suspension_GetState(void *self);
void    vt_Suspension_GetState_Pf(void *self, float *a);
void    vt_Suspension_SetState_Pf(void *self, float *a);
float  *vt_Suspension_GetDerivative_Pf(void *self, float *out);
void    vt_Suspension_ComputeAuxiliaries(void *self);

void    vt_Engine_dtor(void *self, int32_t flags);
int32_t vt_Engine_GetSize(void *self);
float  *vt_Engine_GetState(void *self);
void    vt_Engine_GetState_Pf(void *self, float *a);
void    vt_Engine_SetState_Pf(void *self, float *a);
float  *vt_Engine_GetDerivative_Pf(void *self, float *out);
void    vt_Engine_ComputeAuxiliaries(void *self);

void    vt_DriveTrain_dtor(void *self, int32_t flags);
int32_t vt_DriveTrain_GetSize(void *self);
float  *vt_DriveTrain_GetState(void *self);
void    vt_DriveTrain_GetState_Pf(void *self, float *a);
void    vt_DriveTrain_SetState_Pf(void *self, float *a);
float  *vt_DriveTrain_GetDerivative_Pf(void *self, float *out);
void    vt_DriveTrain_ComputeAuxiliaries(void *self);

void    vt_Ackerman_dtor(void *self, int32_t flags);
void    vt_Ackerman_SetSteering(void *self, uint16_t bam);
void    vt_Steering_dtor(void *self, int32_t flags);

// Installs all seven at their image addresses. The game calls it once at
// boot, after physicssystem_install_vtables; a harness may call it after
// vt_reset() and then replace any of them.
void physcomp_install_vtables(void);

#endif
