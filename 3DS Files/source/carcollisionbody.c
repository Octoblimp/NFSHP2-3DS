// carcollisionbody -- CarCollisionBody, and the DynamicCollisionBody
// method Car reaches; see collisionbody.h.
//
// They are apart from collisionbody.c for the same reason Car is split:
// they need car.h, the movers and the physics, and the base class, the
// static bodies and the witness bookkeeping need none of it.

#include "collisionbody.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "bchunk.h"
#include "bmem.h"
#include "car.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "mellowmover.h"
#include "physicscar.h"
#include "player.h"
#include "race.h"
#include "realtime.h"
#include "rigidbody.h"
#include "terraintype.h"
#include "vtable.h"

int32_t BoringAIForCameraTuningOn;      // 0x0032317c
int32_t WilliamsAITuningMode;           // 0x00324d60

CarDamageAddDamageFn           gCarDamageAddDamageFn;
CopManagerMonitorImpactFn      gCopManagerMonitorImpactFn;
AnimatedDriverBeginCollisionFn gAnimatedDriverBeginCollisionFn;
PortRumbleImpactFn             gPortRumbleImpactFn;
CarStartForceImpactFn          gCarStartForceImpactFn;

// gp-28736 and gp-28728, the same float twice: 1 / 1.3.
#define CAR_MASS_INVERSE_MAX 0.769230783f
// gp-28732 and gp-28724: the inertia's share of an impulse.
#define CAR_INERTIA_SCALE    0.4f
// gp-28720.
#define CAR_DAMAGE_SCALE     0.03f
// gp-28716 and gp-28712.
#define CAR_FRICTION         0.3f
#define CAR_BOUNCINESS       0.1f
// Built with `lui at,0x41a0` and `lui at,0x4080`.
#define CAR_HARD_IMPACT      20.0f
#define CAR_SOFT_IMPACT      4.0f

// gp-28760 .. gp-28740: the box a car with no `_CV` gets, x, y and z each
// high then low.
#define CAR_BOX_XMAX  2.165f
#define CAR_BOX_XMIN -2.217f
#define CAR_BOX_YMAX  0.971f
#define CAR_BOX_YMIN -0.971f
#define CAR_BOX_ZMAX  0.624f
#define CAR_BOX_ZMIN -0.2f

typedef void (*VtSetToPhysicsModeFn)(void *self, CollisionBody *other);

// The image's `Car%d` buffer is sixteen bytes, and bStrCat's 256.
#define CAR_NAME_BYTES 16
#define CAR_CV_BYTES   256

// bStrCat(buf, BaseModelName, "_CV") -- a copy of each, then the NUL -- and
// bStringHash of it.
static uint32_t cv_hash(const Car *car)
{
    char cv[CAR_CV_BYTES];

    snprintf(cv, sizeof cv, "%s_CV", car->pCarTypeInfo->BaseModelName);
    return bchunk_hash(cv);
}

static RigidBody *car_rb(const CarCollisionBody *b)
{
    return (RigidBody *)b->Dynamic.pBody;
}

// `*at` as a point in the car's frame: bTransposeMatrix of the RigidBody's
// rotation, then bMulMatrix (bMulMatrixVec3), whose w of 1 brings in the
// transpose's fourth row -- zero, as R's fourth column is.
static void to_car_frame(const CarCollisionBody *b, bVector3 *out,
                         const bVector3 *at)
{
    bMatrix4 rt;

    bTransposeMatrix(&rt, &car_rb(b)->State.R);
    bMulMatrixVec3(out, &rt, at);
}

CarCollisionBody *carcollisionbody_init(CarCollisionBody *b, Car *car)
{
    DynamicCollisionBody *d = &b->Dynamic;
    CollisionBody *body = &d->Body;
    CollisionStats *s = &TheCollisionStats;
    PipelinePolyhedron *pp;
    char name[CAR_NAME_BYTES];

    dynamiccollisionbody_init(d, collisionbody_get_next_id(),
                              CAR_COLLISION_BODY,
                              &car->TheTopologyCoordinate);
    // The two Timers' constructors zero the stamps first; both are written
    // again below before anything reads them.
    body->_vtable = CARCOLLISIONBODY_VTABLE;
    s->NumCarCollisionBodies++;
    if (s->HighestNumCarCollisionBodies < s->NumCarCollisionBodies)
        s->HighestNumCarCollisionBodies = s->NumCarCollisionBodies;
    b->pCar = car;
    body->ActiveCollisionDetection = 1;
    d->pSystem = NULL;
    d->pBody = NULL;
    b->LastPenetrationTime.PackedTime = (uint32_t)WorldTimer;
    b->LastYawControlCollisionTime.PackedTime = (uint32_t)WorldTimer;

    // bSPrintf, which the port does not have.
    snprintf(name, sizeof name, "Car%d", car->DriverNumber);
    collisionbody_set_debug_name(body, name);

    pp = find_pipeline_polyhedron(cv_hash(car),
                                  &car->pCarTypeInfo->CenterOfGravity);
    if (pp != NULL) {
        body->pPoly = &pp->Poly;
    } else {
        // The two-argument bMalloc(2800, 16), which takes no name.
        RectPolyhedron *r = bMalloc((int)sizeof(RectPolyhedron),
                                    "RectPolyhedron", 0, 16);

        body->pPoly = &rectpoly_init(r, CAR_BOX_XMAX, CAR_BOX_XMIN,
                                     CAR_BOX_YMAX, CAR_BOX_YMIN,
                                     CAR_BOX_ZMAX, CAR_BOX_ZMIN)->Poly;
    }
    dynamiccollisionbody_build_bounding_volumes(d);
    dynamiccollisionbody_update_position(d);
    return b;
}

// VCPolyhedron's destructor is called directly, not through a table, with
// flags 3 whatever the volume is.
void carcollisionbody_destroy(CarCollisionBody *b, int32_t flags)
{
    CollisionBody *body = &b->Dynamic.Body;

    body->_vtable = CARCOLLISIONBODY_VTABLE;
    TheCollisionStats.NumCarCollisionBodies--;
    if (find_pipeline_polyhedron(cv_hash(b->pCar), NULL) == NULL
        && body->pPoly != NULL)
        vcpoly_destroy(body->pPoly, 3);
    dynamiccollisionbody_destroy(&b->Dynamic, 0);
    if (flags & 1)
        carcollisionbody_delete(b);
}

void *carcollisionbody_new(void)
{
    return bSlotOMalloc(CarCollisionBodySlotPool);
}

void carcollisionbody_delete(void *p)
{
    bSlotFree(CarCollisionBodySlotPool, p);
}

bVector3 *carcollisionbody_get_position(CollisionBody *b)
{
    CarCollisionBody *c = (CarCollisionBody *)b;

    if (c->Dynamic.PhysicsMode != 0)
        return (bVector3 *)&car_rb(c)->State.X;
    return &c->pCar->State.Position;
}

bVector3 *carcollisionbody_get_velocity(CollisionBody *b)
{
    CarCollisionBody *c = (CarCollisionBody *)b;

    if (c->Dynamic.PhysicsMode != 0)
        return (bVector3 *)&car_rb(c)->Velocity;
    return &c->pCar->State.Velocity;
}

bMatrix4 *carcollisionbody_get_rotation(CollisionBody *b)
{
    CarCollisionBody *c = (CarCollisionBody *)b;

    if (c->Dynamic.PhysicsMode != 0)
        return &car_rb(c)->State.R;
    return &c->pCar->State.BodyMatrix;
}

void carcollisionbody_move(CollisionBody *b, float t)
{
    CarCollisionBody *c = (CarCollisionBody *)b;
    float done;

    dynamiccollisionbody_begin_move(&c->Dynamic, t);
    done = car_move(c->pCar, t);
    if (done < t) {
        const VtEntry *e =
            vt_slot(b->_vtable, COLLISIONBODY_VT_SET_TO_PHYSICS_MODE);

        ((VtSetToPhysicsModeFn)e->fn)(vt_this(b, e), NULL);
        car_move(c->pCar, t - done);
    }
    dynamiccollisionbody_update_position(&c->Dynamic);
}

float carcollisionbody_consider_impulse(CollisionBody *b, bVector3 *j,
                                        bVector3 *at)
{
    (void)b;
    (void)j;
    (void)at;
    return 1.0f;
}

int32_t carcollisionbody_get_terrain_type(CollisionBody *b)
{
    (void)b;
    return TERRAIN_TYPE_CAR;
}

int32_t carcollisionbody_is_moveable(CollisionBody *b)
{
    (void)b;
    return 1;
}

float carcollisionbody_get_bounciness(CollisionBody *b)
{
    (void)b;
    return CAR_BOUNCINESS;
}

float carcollisionbody_get_friction(CollisionBody *b)
{
    (void)b;
    return CAR_FRICTION;
}

// The VU's vmulx scales all four lanes, pad too; the length is of x, y and
// z, summed as (x*x + y*y) + z*z.
void carcollisionbody_apply_impulse(CollisionBody *b, bVector3 *j,
                                    bVector3 *at)
{
    CarCollisionBody *c = (CarCollisionBody *)b;
    RigidBody *rb = car_rb(c);
    float f = 1.0f;
    float amount;
    bVector3 s;

    if (CAR_MASS_INVERSE_MAX < rb->Mass_inv)
        f = CAR_MASS_INVERSE_MAX / rb->Mass_inv;
    s.x = j->x * f;
    s.y = j->y * f;
    s.z = j->z * f;
    s.pad = j->pad * f;
    rigidbody_apply_impulse_scaled(rb, (const bVector4 *)&s,
                                   (const bVector4 *)at, CAR_INERTIA_SCALE);
    amount = sqrtf((s.x * s.x + s.y * s.y) + s.z * s.z);
    carcollisionbody_add_damage(c, at, amount);
    carcollisionbody_animate_collision_reaction(c, &s, amount);
}

// The rumble's test is RaceCoordinator's IsReplaying and IsDemoMode inlined:
// instant replay, the post-race, auto replay, or IsReplayDemoMode called
// out of line; then the state re-read, less AI_DEMO_MODE, unsigned below 2.
// The second test's replay demo is the first's last, so only the AI demo
// is new to it.
void carcollisionbody_add_damage(CarCollisionBody *b, bVector3 *at,
                                 float amount)
{
    Car *car = b->pCar;

    if (car->pCarDamage != NULL) {
        bVector3 local;

        to_car_frame(b, &local, at);
        if (gCarDamageAddDamageFn == NULL) {
            fprintf(stderr, "carcollisionbody_add_damage: "
                            "no CarDamage::AddDamage\n");
            abort();
        }
        gCarDamageAddDamageFn(car->pCarDamage, &local,
                              amount * CAR_DAMAGE_SCALE);
    }

    car = b->pCar;
    if (car->pPlayer != NULL && pRaceCoordinator != NULL) {
        RCState st = racecoordinator_get_current_state(pRaceCoordinator);

        if (st != RCSTATE_INSTANT_REPLAY && st != RCSTATE_POSTRACE
            && st != RCSTATE_AUTO_REPLAY
            && !racecoordinator_is_replay_demo_mode(pRaceCoordinator)
            && (uint32_t)racecoordinator_get_current_state(pRaceCoordinator)
                   - (uint32_t)RCSTATE_AI_DEMO_MODE >= 2u
            && gPortRumbleImpactFn != NULL)
            gPortRumbleImpactFn(car->pPlayer->JoyPort, amount);
    }

    if (pCopManager != NULL) {
        if (gCopManagerMonitorImpactFn == NULL) {
            fprintf(stderr, "carcollisionbody_add_damage: "
                            "no tCopManager::MonitorImpact\n");
            abort();
        }
        gCopManagerMonitorImpactFn(pCopManager, b, amount);
    }
}

static void begin_collision(AnimatedDriver *ad, int32_t type,
                            int32_t priority)
{
    if (gAnimatedDriverBeginCollisionFn == NULL) {
        fprintf(stderr, "carcollisionbody_animate_collision_reaction: "
                        "no AnimatedDriver::BeginCollision\n");
        abort();
    }
    gAnimatedDriverBeginCollisionFn(ad, type, priority);
}

void carcollisionbody_animate_collision_reaction(CarCollisionBody *b,
                                                 bVector3 *j, float amount)
{
    AnimatedDriver *ad = b->pCar->pAnimatedDriver;
    bVector3 local;

    if (ad != NULL) {
        if (CAR_HARD_IMPACT < amount) {
            int32_t type;

            to_car_frame(b, &local, j);
            if (fabsf(local.y) < fabsf(local.x))
                type = 0.0f < local.x ? DRIVER_ANIMATION_TYPE_COLLISION_BACK
                                      : DRIVER_ANIMATION_TYPE_COLLISION_FRONT;
            else
                type = 0.0f < local.y ? DRIVER_ANIMATION_TYPE_COLLISION_LEFT
                                      : DRIVER_ANIMATION_TYPE_COLLISION_RIGHT;
            begin_collision(ad, type, 3);
        } else if (CAR_SOFT_IMPACT < amount) {
            begin_collision(ad, DRIVER_ANIMATION_TYPE_COLLISION_LIGHT, 2);
        }
    }

    if (b->pCar->pPlayer != NULL && CAR_SOFT_IMPACT < amount) {
        to_car_frame(b, &local, j);
        if (gCarStartForceImpactFn != NULL) {
            bVector3 copy = local;

            gCarStartForceImpactFn(b->pCar, &copy, amount);
        }
    }
}

int32_t carcollisionbody_are_collisions_enabled(CollisionBody *b)
{
    if (BoringAIForCameraTuningOn != 0 || WilliamsAITuningMode != 0)
        return 0;
    return b->CollisionsDisabled == 0;
}

// `c.lt.s` then `mov.s` on true: a NaN inverse mass is answered as it is.
float carcollisionbody_get_mass_inverse(CollisionBody *b)
{
    float m = car_rb((CarCollisionBody *)b)->Mass_inv;

    if (CAR_MASS_INVERSE_MAX < m)
        m = CAR_MASS_INVERSE_MAX;
    return m;
}

static void scale_row(bVector4 *o, const bVector4 *v)
{
    o->x = v->x * CAR_INERTIA_SCALE;
    o->y = v->y * CAR_INERTIA_SCALE;
    o->z = v->z * CAR_INERTIA_SCALE;
    o->w = v->w * CAR_INERTIA_SCALE;
}

bMatrix4 *carcollisionbody_get_inertia_tensor_inverse(CollisionBody *b)
{
    CarCollisionBody *c = (CarCollisionBody *)b;
    const bMatrix4 *in = &car_rb(c)->I_body_inv;
    bMatrix4 *out = &c->ScaledInverseInertiaTensor;

    scale_row(&out->v0, &in->v0);
    scale_row(&out->v1, &in->v1);
    scale_row(&out->v2, &in->v2);
    out->v3 = in->v3;
    return out;
}

int32_t carcollisionbody_is_blinking(CollisionBody *b)
{
    Car *car = ((CarCollisionBody *)b)->pCar;

    return car_is_blinking(car) || car_is_poofed(car);
}

void carcollisionbody_setup_physics_pointers(CarCollisionBody *b)
{
    DynamicCollisionBody *d = &b->Dynamic;
    Car *car;

    d->pSystem = NULL;
    d->pBody = NULL;
    if (d->PhysicsMode == 0)
        return;

    car = b->pCar;
    if (car->TheMovementMode != PHYSICS_MOVEMENT
        && car->TheMovementMode != MELLOW_MOVEMENT)
        return;
    if (car->pCarMover == NULL) {
        fprintf(stderr, "carcollisionbody_setup_physics_pointers: "
                        "no mover\n");
        abort();
    }

    // The image does not look at which of the two it is: both put the
    // PhysicsSystem at 8 and the RigidBody at 24.
    if (car->TheMovementMode == PHYSICS_MOVEMENT) {
        PhysicsCar *pc = (PhysicsCar *)car->pCarMover;
        d->pSystem = &pc->Vehicle;
        d->pBody = pc->pBody;
    } else {
        MellowMover *mm = (MellowMover *)car->pCarMover;
        d->pSystem = &mm->Vehicle;
        d->pBody = mm->pBody;
    }
}

void carcollisionbody_set_to_physics_mode(CarCollisionBody *b,
                                          CollisionBody *other)
{
    Car *them = NULL;

    if (other != NULL && other->Type == 0)
        them = ((CarCollisionBody *)other)->pCar;
    car_set_to_physics_mode(b->pCar, them);
    carcollisionbody_setup_physics_pointers(b);
}

float dynamiccollisionbody_get_distance_and_speed(float *speed,
                                                  DynamicCollisionBody *a,
                                                  DynamicCollisionBody *b)
{
    (void)a;
    (void)b;
    *speed = 0.0f;
    return *speed;
}

// ------------------------------------------------------------- the table

#define E(f) { 0, 0, (VtFn)(f) }
#define PURE { 0, 0, NULL }

// _vt$16CarCollisionBody (0x0029bc08). Every entry's delta is 0.
static const VtEntry carcollisionbody_vt[COLLISIONBODY_VT_ENTRIES] = {
    PURE,
    E(carcollisionbody_destroy),
    PURE,                                           // DoSnapshot
    E(carcollisionbody_get_position),
    E(carcollisionbody_get_velocity),
    E(carcollisionbody_get_rotation),
    E(dynamiccollisionbody_set_position),
    E(dynamiccollisionbody_get_max_backup_time),
    E(carcollisionbody_move),
    E(dynamiccollisionbody_backup),
    E(dynamiccollisionbody_interpolate),
    E(dynamiccollisionbody_recompute_auxilliaries),
    E(dynamiccollisionbody_get_current_velocities),
    E(dynamiccollisionbody_get_test_impulse_velocities),
    E(carcollisionbody_set_to_physics_mode),
    E(carcollisionbody_consider_impulse),
    E(carcollisionbody_apply_impulse),
    E(carcollisionbody_are_collisions_enabled),
    E(carcollisionbody_get_terrain_type),
    E(carcollisionbody_get_mass_inverse),
    E(carcollisionbody_get_inertia_tensor_inverse),
    E(carcollisionbody_is_moveable),
    E(dynamiccollisionbody_change_in_energy),
    E(carcollisionbody_is_blinking),
    E(carcollisionbody_get_bounciness),
    E(carcollisionbody_get_friction),
};

void carcollisionbody_install_vtable(void)
{
    vt_install(CARCOLLISIONBODY_VTABLE, carcollisionbody_vt,
               COLLISIONBODY_VT_ENTRIES);
}
