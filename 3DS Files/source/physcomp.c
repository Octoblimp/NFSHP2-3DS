// physcomp -- see physcomp.h.

#include "physcomp.h"

#include <stdlib.h>

#include "bmem.h"
#include "carmodes.h"
#include "mellowmover.h"
#include "vtable.h"

// ------------------------------------------------------------- the pools

BSlotPool *RigidBodySlotPool;
BSlotPool *TwoWheelAckermanSteeringSlotPool;
BSlotPool *WheelSlotPool;
BSlotPool *EngineSlotPool;
BSlotPool *DriveTrainSlotPool;
BSlotPool *AerodynamicsSlotPool;
BSlotPool *SuspensionSlotPool;
BSlotPool *MellovatorSlotPool;
BSlotPool *MellowMoverSlotPool;
BSlotPool *NullMoverSlotPool;

// The last argument of every call, `addiu a3,zero,16`.
#define PHYSICS_MEMORY_POOL 16

void InitPhysics(int32_t numDriverInfo)
{
    int32_t n = numDriverInfo;

    // `addiu a1,s0,32` and `sll s1,s0,2` -- the only two counts that are
    // not n itself.
    RigidBodySlotPool = bNewSlotPool((int)sizeof(RigidBody), n + 32,
                                     "RigidBodySlotPool",
                                     PHYSICS_MEMORY_POOL);
    TwoWheelAckermanSteeringSlotPool =
        bNewSlotPool((int)sizeof(TwoWheelAckermanSteering), n,
                     "TwoWheelAckermanSteeringSlotPool",
                     PHYSICS_MEMORY_POOL);
    WheelSlotPool = bNewSlotPool((int)sizeof(Wheel), n * 4,
                                 "WheelSlotPool", PHYSICS_MEMORY_POOL);
    EngineSlotPool = bNewSlotPool((int)sizeof(Engine), n,
                                  "EngineSlotPool", PHYSICS_MEMORY_POOL);
    DriveTrainSlotPool = bNewSlotPool((int)sizeof(DriveTrain), n,
                                      "DriveTrainSlotPool",
                                      PHYSICS_MEMORY_POOL);
    AerodynamicsSlotPool = bNewSlotPool((int)sizeof(Aerodynamics), n,
                                        "AerodynamicsSlotPool",
                                        PHYSICS_MEMORY_POOL);
    SuspensionSlotPool = bNewSlotPool((int)sizeof(Suspension), n * 4,
                                      "SuspensionSlotPool",
                                      PHYSICS_MEMORY_POOL);
    MellovatorSlotPool = bNewSlotPool((int)sizeof(Mellovator), n,
                                      "MellovatorSlotPool",
                                      PHYSICS_MEMORY_POOL);
    MellowMoverSlotPool = bNewSlotPool((int)sizeof(MellowMover), n,
                                       "MellowMoverSlotPool",
                                       PHYSICS_MEMORY_POOL);
    NullMoverSlotPool = bNewSlotPool((int)sizeof(NullMover), n,
                                     "NullMoverSlotPool",
                                     PHYSICS_MEMORY_POOL);
}

void ClosePhysics(void)
{
    bDeleteSlotPool(RigidBodySlotPool);
    bDeleteSlotPool(TwoWheelAckermanSteeringSlotPool);
    bDeleteSlotPool(WheelSlotPool);
    bDeleteSlotPool(EngineSlotPool);
    bDeleteSlotPool(DriveTrainSlotPool);
    bDeleteSlotPool(AerodynamicsSlotPool);
    bDeleteSlotPool(SuspensionSlotPool);
    bDeleteSlotPool(MellovatorSlotPool);
    bDeleteSlotPool(MellowMoverSlotPool);
    bDeleteSlotPool(NullMoverSlotPool);

    RigidBodySlotPool = NULL;
    TwoWheelAckermanSteeringSlotPool = NULL;
    WheelSlotPool = NULL;
    EngineSlotPool = NULL;
    DriveTrainSlotPool = NULL;
    AerodynamicsSlotPool = NULL;
    SuspensionSlotPool = NULL;
    MellovatorSlotPool = NULL;
    MellowMoverSlotPool = NULL;
    NullMoverSlotPool = NULL;
}

// ----------------------------------------------------- operator new/delete

RigidBody *rigidbody_new(void)
{
    return (RigidBody *)bSlotOMalloc(RigidBodySlotPool);
}

Wheel *wheel_new(void)
{
    return (Wheel *)bSlotOMalloc(WheelSlotPool);
}

Suspension *suspension_new(void)
{
    return (Suspension *)bSlotOMalloc(SuspensionSlotPool);
}

Engine *engine_new(void)
{
    return (Engine *)bSlotOMalloc(EngineSlotPool);
}

DriveTrain *drivetrain_new(void)
{
    return (DriveTrain *)bSlotOMalloc(DriveTrainSlotPool);
}

TwoWheelAckermanSteering *ackerman_new(void)
{
    return (TwoWheelAckermanSteering *)
        bSlotOMalloc(TwoWheelAckermanSteeringSlotPool);
}

Aerodynamics *aerodynamics_new(void)
{
    return (Aerodynamics *)bSlotOMalloc(AerodynamicsSlotPool);
}

void rigidbody_delete(void *p)   { bSlotFree(RigidBodySlotPool, p); }
void wheel_delete(void *p)       { bSlotFree(WheelSlotPool, p); }
void suspension_delete(void *p)  { bSlotFree(SuspensionSlotPool, p); }
void engine_delete(void *p)      { bSlotFree(EngineSlotPool, p); }
void drivetrain_delete(void *p)  { bSlotFree(DriveTrainSlotPool, p); }
void aerodynamics_delete(void *p) { bSlotFree(AerodynamicsSlotPool, p); }

void ackerman_delete(void *p)
{
    bSlotFree(TwoWheelAckermanSteeringSlotPool, p);
}

// ------------------------------------------------------- the destructors

void (*gSkidSetFinishedAddingFn)(void *skidSet);

void skidmaker_destroy(SkidMaker *sm, int32_t flags)
{
    // MakeNoSkid, `lw a0,0(a0) ; beq a0,zero`.
    if (sm->pSkidSet != NULL) {
        if (gSkidSetFinishedAddingFn == NULL)
            abort();
        gSkidSetFinishedAddingFn(sm->pSkidSet);
    }

    if (flags & 1)
        bFree(sm);
}

void rigidbody_destroy(RigidBody *rb, int32_t flags)
{
    rigidbody_fini(rb);
    if (flags & 1)
        rigidbody_delete(rb);
}

void wheel_destroy(Wheel *w, int32_t flags)
{
    // `addiu a0,s1,384 ; jal _$_9SkidMaker ; addiu a1,zero,2` -- the
    // member's destructor with the delete bit clear, before the base's.
    skidmaker_destroy(&w->TheSkidMaker, 2);
    physicscomponent_fini(w);
    if (flags & 1)
        wheel_delete(w);
}

void suspension_destroy(Suspension *s, int32_t flags)
{
    suspension_fini(s);
    if (flags & 1)
        suspension_delete(s);
}

void engine_destroy(Engine *e, int32_t flags)
{
    // `sw v0,8(s1)` with _vt$6Engine, before the base's store over it.
    e->_vtable = ENGINE_VTABLE;
    physicscomponent_fini(e);
    if (flags & 1)
        engine_delete(e);
}

void drivetrain_destroy(DriveTrain *d, int32_t flags)
{
    physicscomponent_fini(d);
    if (flags & 1)
        drivetrain_delete(d);
}

void ackerman_destroy(TwoWheelAckermanSteering *a, int32_t flags)
{
    // Both vptr stores and the `jal _$_8Steering` with a1 = 0.
    ackerman_fini(a);
    if (flags & 1)
        ackerman_delete(a);
}

void steering_destroy(Steering *s, int32_t flags)
{
    steering_fini(s);
    if (flags & 1)
        bFree(s);
}

// ------------------------------------------------------------ the entries

void vt_RigidBody_dtor(void *self, int32_t flags)
{
    rigidbody_destroy((RigidBody *)self, flags);
}

int32_t vt_RigidBody_GetSize(void *self)
{
    return rigidbody_get_size((const RigidBody *)self);
}

float *vt_RigidBody_GetState(void *self)
{
    return (float *)rigidbody_get_state((RigidBody *)self);
}

void vt_RigidBody_GetState_Pf(void *self, float *a)
{
    rigidbody_get_state_array((const RigidBody *)self, a);
}

void vt_RigidBody_SetState_Pf(void *self, float *a)
{
    rigidbody_set_state_array((RigidBody *)self, a);
}

void vt_RigidBody_ResolveForces(void *self)
{
    rigidbody_resolve_forces((RigidBody *)self);
}

float *vt_RigidBody_GetDerivative_Pf(void *self, float *out)
{
    return rigidbody_get_derivative((RigidBody *)self, out);
}

void vt_RigidBody_ComputeAuxiliaries(void *self)
{
    rigidbody_compute_auxiliaries((RigidBody *)self);
}

void vt_Wheel_dtor(void *self, int32_t flags)
{
    wheel_destroy((Wheel *)self, flags);
}

int32_t vt_Wheel_GetSize(void *self)
{
    return wheel_get_size((const Wheel *)self);
}

float *vt_Wheel_GetState(void *self)
{
    return (float *)wheel_get_state((Wheel *)self);
}

void vt_Wheel_GetState_Pf(void *self, float *a)
{
    wheel_get_state_array((const Wheel *)self, a);
}

void vt_Wheel_SetState_Pf(void *self, float *a)
{
    wheel_set_state_array((Wheel *)self, a);
}

float *vt_Wheel_GetDerivative_Pf(void *self, float *out)
{
    return wheel_get_derivative((Wheel *)self, out);
}

void vt_Wheel_ComputeAuxiliaries(void *self)
{
    wheel_compute_auxiliaries((Wheel *)self);
}

void vt_Suspension_dtor(void *self, int32_t flags)
{
    suspension_destroy((Suspension *)self, flags);
}

int32_t vt_Suspension_GetSize(void *self)
{
    return suspension_get_size((const Suspension *)self);
}

float *vt_Suspension_GetState(void *self)
{
    return (float *)suspension_get_state((Suspension *)self);
}

void vt_Suspension_GetState_Pf(void *self, float *a)
{
    suspension_get_state_array((const Suspension *)self, a);
}

void vt_Suspension_SetState_Pf(void *self, float *a)
{
    suspension_set_state_array((Suspension *)self, a);
}

float *vt_Suspension_GetDerivative_Pf(void *self, float *out)
{
    return suspension_get_derivative((Suspension *)self, out);
}

void vt_Suspension_ComputeAuxiliaries(void *self)
{
    suspension_compute_auxiliaries((Suspension *)self);
}

void vt_Engine_dtor(void *self, int32_t flags)
{
    engine_destroy((Engine *)self, flags);
}

int32_t vt_Engine_GetSize(void *self)
{
    return engine_get_size((const Engine *)self);
}

float *vt_Engine_GetState(void *self)
{
    return (float *)engine_get_state((const Engine *)self);
}

void vt_Engine_GetState_Pf(void *self, float *a)
{
    engine_get_state_f((const Engine *)self, a);
}

void vt_Engine_SetState_Pf(void *self, float *a)
{
    engine_set_state_f((Engine *)self, a);
}

float *vt_Engine_GetDerivative_Pf(void *self, float *out)
{
    (void)engine_get_derivative((Engine *)self, out);
    return NULL;
}

void vt_Engine_ComputeAuxiliaries(void *self)
{
    engine_compute_auxiliaries((Engine *)self);
}

void vt_DriveTrain_dtor(void *self, int32_t flags)
{
    drivetrain_destroy((DriveTrain *)self, flags);
}

int32_t vt_DriveTrain_GetSize(void *self)
{
    return drivetrain_get_size((const DriveTrain *)self);
}

float *vt_DriveTrain_GetState(void *self)
{
    return (float *)drivetrain_get_state((DriveTrain *)self);
}

void vt_DriveTrain_GetState_Pf(void *self, float *a)
{
    drivetrain_get_state_array((const DriveTrain *)self, a);
}

void vt_DriveTrain_SetState_Pf(void *self, float *a)
{
    drivetrain_set_state_array((DriveTrain *)self, a);
}

float *vt_DriveTrain_GetDerivative_Pf(void *self, float *out)
{
    (void)drivetrain_get_derivative((const DriveTrain *)self, out);
    return NULL;
}

void vt_DriveTrain_ComputeAuxiliaries(void *self)
{
    drivetrain_compute_auxiliaries((DriveTrain *)self);
}

void vt_Ackerman_dtor(void *self, int32_t flags)
{
    ackerman_destroy((TwoWheelAckermanSteering *)self, flags);
}

void vt_Ackerman_SetSteering(void *self, uint16_t bam)
{
    ackerman_set_steering((TwoWheelAckermanSteering *)self, bam);
}

void vt_Ackerman_DoSnapshot(void *self, void *snap)
{
    ackerman_do_snapshot((TwoWheelAckermanSteering *)self, snap);
}

void vt_Steering_dtor(void *self, int32_t flags)
{
    steering_destroy((Steering *)self, flags);
}

// ------------------------------------------------------------ the tables

static const VtEntry rigidbody_vt[RIGIDBODY_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_RigidBody_dtor },
    { 0, 0, (VtFn)vt_RigidBody_GetSize },
    { 0, 0, (VtFn)vt_RigidBody_GetState },
    { 0, 0, (VtFn)vt_RigidBody_GetState_Pf },
    { 0, 0, (VtFn)vt_RigidBody_SetState_Pf },
    { 0, 0, (VtFn)vt_RigidBody_ResolveForces },
    { 0, 0, (VtFn)vt_RigidBody_GetDerivative_Pf },
    { 0, 0, (VtFn)vt_RigidBody_ComputeAuxiliaries },
};

static const VtEntry wheel_vt[WHEEL_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_Wheel_dtor },
    { 0, 0, (VtFn)vt_Wheel_GetSize },
    { 0, 0, (VtFn)vt_Wheel_GetState },
    { 0, 0, (VtFn)vt_Wheel_GetState_Pf },
    { 0, 0, (VtFn)vt_Wheel_SetState_Pf },
    { 0, 0, (VtFn)physicscomponent_resolve_forces },
    { 0, 0, (VtFn)vt_Wheel_GetDerivative_Pf },
    { 0, 0, (VtFn)vt_Wheel_ComputeAuxiliaries },
};

static const VtEntry suspension_vt[SUSPENSION_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_Suspension_dtor },
    { 0, 0, (VtFn)vt_Suspension_GetSize },
    { 0, 0, (VtFn)vt_Suspension_GetState },
    { 0, 0, (VtFn)vt_Suspension_GetState_Pf },
    { 0, 0, (VtFn)vt_Suspension_SetState_Pf },
    { 0, 0, (VtFn)physicscomponent_resolve_forces },
    { 0, 0, (VtFn)vt_Suspension_GetDerivative_Pf },
    { 0, 0, (VtFn)vt_Suspension_ComputeAuxiliaries },
};

static const VtEntry engine_vt[ENGINE_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_Engine_dtor },
    { 0, 0, (VtFn)vt_Engine_GetSize },
    { 0, 0, (VtFn)vt_Engine_GetState },
    { 0, 0, (VtFn)vt_Engine_GetState_Pf },
    { 0, 0, (VtFn)vt_Engine_SetState_Pf },
    { 0, 0, (VtFn)physicscomponent_resolve_forces },
    { 0, 0, (VtFn)vt_Engine_GetDerivative_Pf },
    { 0, 0, (VtFn)vt_Engine_ComputeAuxiliaries },
};

static const VtEntry drivetrain_vt[DRIVETRAIN_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_DriveTrain_dtor },
    { 0, 0, (VtFn)vt_DriveTrain_GetSize },
    { 0, 0, (VtFn)vt_DriveTrain_GetState },
    { 0, 0, (VtFn)vt_DriveTrain_GetState_Pf },
    { 0, 0, (VtFn)vt_DriveTrain_SetState_Pf },
    { 0, 0, (VtFn)physicscomponent_resolve_forces },
    { 0, 0, (VtFn)vt_DriveTrain_GetDerivative_Pf },
    { 0, 0, (VtFn)vt_DriveTrain_ComputeAuxiliaries },
};

static const VtEntry ackerman_vt[STEERING_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_Ackerman_dtor },
    { 0, 0, (VtFn)vt_Ackerman_SetSteering },
    { 0, 0, (VtFn)vt_Ackerman_DoSnapshot },
};

// The two NULLs are the base's __pure_virtual entries.
static const VtEntry steering_vt[STEERING_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_Steering_dtor },
    { 0, 0, NULL },
    { 0, 0, NULL },
};

void physcomp_install_vtables(void)
{
    vt_install(RIGIDBODY_VTABLE, rigidbody_vt, RIGIDBODY_VT_ENTRIES);
    vt_install(WHEEL_VTABLE, wheel_vt, WHEEL_VT_ENTRIES);
    vt_install(SUSPENSION_VTABLE, suspension_vt, SUSPENSION_VT_ENTRIES);
    vt_install(ENGINE_VTABLE, engine_vt, ENGINE_VT_ENTRIES);
    vt_install(DRIVETRAIN_VTABLE, drivetrain_vt, DRIVETRAIN_VT_ENTRIES);
    vt_install(ACKERMAN_VTABLE, ackerman_vt, STEERING_VT_ENTRIES);
    vt_install(STEERING_VTABLE, steering_vt, STEERING_VT_ENTRIES);
}
