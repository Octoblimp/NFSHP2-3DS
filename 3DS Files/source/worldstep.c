// worldstep -- see world.h, "the timestep". World.obj's clock, pause, time
// scale, car table, checksums and step. docs/formats/world.md has the
// decode.

#include "world.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "blist.h"
#include "bmath.h"
#include "bticker.h"
#include "car.h"
#include "chopper.h"
#include "collision.h"
#include "collisionbody.h"
#include "joylog.h"
#include "player.h"
#include "race.h"
#include "rain.h"
#include "realtime.h"
#include "replay.h"
#include "smokeable.h"
#include "trackpath.h"
#include "vtable.h"

void (*gTrafficTeleporterDoTimestepFn)(struct TrafficTeleporter *t, float dt);
void (*gGlobalCopThinkFn)(float dt);
void (*gCarDoWheelForcesFn)(Car *c);
void (*gChopperFlyFn)(struct Chopper *h, float dt);
void (*gCarFinishMovementFn)(Car *c, float dt);
void (*gCarTriggerEventsFn)(Car *c);
void (*gCarMaybeCameraShakeFn)(Car *c);
void (*gCarMaybeRumbleFn)(Car *c);
void (*gServiceParticleGroupsFn)(void);
void (*gWorldEffectsTweakerCheckFn)(void);
void (*gWorldEffectsDoTimeStepFn)(float dt);
void (*gEmProcessAllEventsFn)(void);
void (*gUpdatePlayersGameStateFn)(void);
void (*gServiceFernFlattenersFn)(void);
void (*gServiceTweakerDamageFn)(void);
void (*gServiceTrackRouteEditorFn)(void);
void (*gRaceUpdateFn)(struct Race *r);
void (*gRaceCoordinatorPostMessageFn)(struct RaceCoordinator *rc,
                                      int32_t msg, int32_t param);
Car *(*gTrafficTeleporterPlaceNewCarFn)(struct TrafficTeleporter *t,
                                        DriverInfo *info);

int32_t (*gSmokeableBreakFn)(Smokeable *s, DynamicCollisionBody **pieces);
void (*gDeleteFarAwaySmokeableCollisionBodiesFn)(void);

#define BODY_END    ((CollisionBody *)(void *)&CollisionBodyList)
#define WITNESS_END ((CollisionBodyWitness *)(void *)&CollisionBodyWitnessList)

// The image's constants: gp-31512, gp-31508 and gp-31504.
#define MAX_TIME_TO_WASTE 0.3f
#define TICKS_TO_SECONDS  0.001f
#define NO_PLAYER         9999999.0f

static void world_fail(const char *what)
{
    fprintf(stderr, "world: %s\n", what);
    abort();
}

// `min.s` and `max.s`, fs then ft.
static float min_s(float fs, float ft)
{
    return ft < fs ? ft : fs;
}

static float max_s(float fs, float ft)
{
    return fs < ft ? ft : fs;
}

// ------------------------------------------------- the step's profile

// Not in the image; see world.h. Each mark gives the ticks since the last
// one to its part.
int32_t       WorldStepProfOn;
WorldStepProf WorldStepProfile;

static uint32_t ProfStart;
static uint32_t ProfLast;

static void prof_start(void)
{
    if (WorldStepProfOn)
        ProfStart = ProfLast = bGetTicker();
}

static void prof_mark(int32_t part)
{
    uint32_t now;

    if (!WorldStepProfOn)
        return;
    now = bGetTicker();
    WorldStepProfile.ticks[part] += now - ProfLast;
    ProfLast = now;
}

static void prof_end(void)
{
    prof_mark(WSP_REST);
    if (WorldStepProfOn) {
        WorldStepProfile.steps++;
        if (ProfLast - ProfStart > WorldStepProfile.worst)
            WorldStepProfile.worst = ProfLast - ProfStart;
    }
}

static void prof_witnesses(void)
{
    CollisionBodyWitness *wit;

    if (!WorldStepProfOn)
        return;
    for (wit = CollisionBodyWitnessList.next; wit != WITNESS_END;
         wit = wit->Link.next)
        WorldStepProfile.witnesses++;
}

static void prof_rounds(int32_t round)
{
    if (!WorldStepProfOn)
        return;
    WorldStepProfile.rounds += (uint32_t)round;
    if ((uint32_t)round > WorldStepProfile.roundsMax)
        WorldStepProfile.roundsMax = (uint32_t)round;
}

// ------------------------------------------------- the fall trace

// Not in the image; see world.h.
int32_t       WorldFallTraceOn;
WorldFallStep WorldFallTrace;
WorldVerifyMissed WorldVerifyMiss;

typedef bVector3 *(*FallVectorFn)(void *self);

// The body's GetPosition and GetVelocity, through its table: the checkers
// that link this file have no CarCollisionBody.
static bVector3 *fall_vector(CollisionBody *b, int32_t slot)
{
    const VtEntry *e = vt_slot(b->_vtable, slot);

    return ((FallVectorFn)e->fn)(vt_this(b, e));
}

#define fall_position(b) fall_vector((b), COLLISIONBODY_VT_GET_POSITION)
#define fall_velocity(b) fall_vector((b), COLLISIONBODY_VT_GET_VELOCITY)

// Player 1's car's body, while the trace is on.
static CollisionBody *fall_body(World *w)
{
    Car *c;

    if (!WorldFallTraceOn || w->TotalNumCars < 1)
        return NULL;
    c = w->CarTable[0];
    if (c == NULL || c->pDynamicCollisionBody == NULL)
        return NULL;
    return &c->pDynamicCollisionBody->Dynamic.Body;
}

static int32_t fall_count(ContactNode *list, CollisionBody *fb)
{
    Contact *c;
    int32_t n = 0;

    for (c = list->next; c != (Contact *)(void *)list; c = c->Link.next)
        if (c->pBody1 == fb || c->pBody2 == fb)
            n++;
    return n;
}

static WorldFallContact *fall_contact_begin(CollisionBody *fb, Contact *c,
                                            int32_t round)
{
    WorldFallStep *s = &WorldFallTrace;
    WorldFallContact *e;
    CollisionBody *other;
    float sign;

    if (fb == NULL || (c->pBody1 != fb && c->pBody2 != fb))
        return NULL;
    if (s->resolved++ >= WORLD_FALL_CONTACTS)
        return NULL;
    e = &s->contact[s->resolved - 1];
    other = c->pBody1 == fb ? c->pBody2 : c->pBody1;
    sign = c->pBody1 == fb ? -1.0f : 1.0f;
    e->round = round;
    e->other = other->Type;
    e->normalZ = 0.0f;
    e->side = 0.0f;
    if (other->Type == TRACK_POLYGON_COLLISION_BODY) {
        const VCPlane *pl = &other->pPoly->pFaces->Plane;
        const bVector3 *p = fall_position(fb);

        e->normalZ = pl->CompressedNormal[2];
        e->side = (pl->CompressedNormal[0] * p->x
                   + pl->CompressedNormal[1] * p->y
                   + pl->CompressedNormal[2] * p->z)
                - pl->CompressedPlaneDistance;
    }
    e->backup = c->BackupTime;
    e->crowbarZ = sign * c->CrowbarVector.z;
    e->zBefore = fall_position(fb)->z;
    e->vzBefore = fall_velocity(fb)->z;
    return e;
}

static void fall_contact_end(CollisionBody *fb, WorldFallContact *e)
{
    if (e == NULL)
        return;
    e->zAfter = fall_position(fb)->z;
    e->vzAfter = fall_velocity(fb)->z;
}

// A car's think or drive, its ticks added to its CarIndex's.
static void prof_car(void (*fn)(Car *c, float dt), uint32_t *by_car, Car *c,
                     float dt)
{
    uint32_t t0;

    if (!WorldStepProfOn) {
        fn(c, dt);
        return;
    }
    t0 = bGetTicker();
    fn(c, dt);
    if (c->CarIndex >= 0 && c->CarIndex < WORLD_MAX_CARS)
        by_car[c->CarIndex] += bGetTicker() - t0;
}

// ----------------------------------------------------- the clock and pause

void world_set_time_scale(World *w, float scale, float timer,
                          void (*callback)(int32_t), int32_t param)
{
    w->TimeScaleCallbackParam = param;
    w->fTimeScale = scale;
    w->fTimeScaleTimer = timer;
    w->TimeScaleCallback = callback;
}

void world_reset_time_scale(World *w)
{
    w->TimeScaleCallbackParam = 0;
    w->fTimeScale = 1.0f;
    w->fTimeScaleTimer = 0.0f;
    w->fTimeToRemainPaused = 0.0f;
    w->TimeScaleCallback = NULL;
}

void world_set_world_paused(World *w, float seconds,
                            void (*callback)(int32_t), int32_t param)
{
    w->TimeScaleCallbackParam = param;
    w->fTimeToRemainPaused = seconds;
    w->TimeScaleCallback = callback;
}

void world_begin_pause(World *w)
{
    (void)w;
}

void world_end_pause(World *w)
{
    (void)w;
}

void world_update_world_paused(World *w)
{
    float t = w->fTimeToRemainPaused;

    if (!(0.0f < t))
        return;
    t = t - RealTimeElapsed;
    w->fTimeToRemainPaused = t;
    if (!(t <= 0.0f))
        return;
    w->fTimeToRemainPaused = 0.0f;
    if (w->TimeScaleCallback != NULL) {
        w->TimeScaleCallback(w->TimeScaleCallbackParam);
        w->TimeScaleCallbackParam = 0;
        w->TimeScaleCallback = NULL;
    }
}

int32_t world_is_world_paused(const World *w)
{
    return 0.0f < w->fTimeToRemainPaused || TweakerPauseWorld != 0;
}

float world_get_timestep(World *w)
{
    ReplayManager *rm = pReplayManager;
    int32_t q;
    float real;

    if (rm->ReplayingFlag) {
        q = ReplayManager_GetData(rm, 8, 1);
    } else {
        q = RealTimeElapsedQuantized;
        if (rm->CapturingFlag)
            ReplayManager_AddData(rm, q, 8, 1);
    }
    real = GetRealTimeElapsedFromQuantized(q);

    // The flag is read again, through pReplayManager again. Retail's
    // (0x0014d718) reads the slow motion and the pause beside it: a replay
    // in either takes its step without the wait, and PreviousTimeToWaste
    // stays as it was.
    rm = pReplayManager;
    if (rm->ReplayingFlag && !rm->SlowMotionFlag && !rm->PausedFlag) {
        float waste = min_s(MAX_TIME_TO_WASTE,
                            max_s((real - RealTimeElapsed)
                                  + w->PreviousTimeToWaste, 0.0f));

        w->PreviousTimeToWaste = waste;
        if (0.0f < waste) {
            uint32_t start = bGetTicker();

            while (bGetTickerDifference(start, bGetTicker())
                   * TICKS_TO_SECONDS < waste)
                ;
        }
    }

    if (0.0f < w->fTimeScaleTimer) {
        float t = w->fTimeScaleTimer - real;

        w->fTimeScaleTimer = t;
        if (t <= 0.0f) {
            w->fTimeScaleTimer = 0.0f;
            w->fTimeScale = 1.0f;
            if (w->TimeScaleCallback != NULL) {
                w->TimeScaleCallback(w->TimeScaleCallbackParam);
                w->TimeScaleCallback = NULL;
                w->TimeScaleCallbackParam = 0;
            }
        }
    }
    return real * w->fTimeScale;
}

// ------------------------------------------------------------ small things

void world_flush_collisions(World *w)
{
    (void)w;
}

int32_t world_random_i(World *w, int32_t range)
{
    return bRandomI(range, &w->WorldRandomSeed);
}

float world_random_f(World *w, float f)
{
    return bRandomF(f, &w->WorldRandomSeed);
}

float world_get_dat_to_closest_player(const World *w, float dat)
{
    float d0 = trackpath_compare_distances(&TheTrackPathManager,
                                           w->PlayerDATs[0], dat);
    float d1 = trackpath_compare_distances(&TheTrackPathManager,
                                           w->PlayerDATs[1], dat);

    return fabsf(d0) < fabsf(d1) ? d0 : d1;
}

// ------------------------------------------------------------ the car table

#define CAR_END(w) ((Car *)(void *)&(w)->CarList)

static int32_t car_type(const Car *c)
{
    return (int32_t)c->MyDriver->TheDriverType;
}

static void add_car(World *w, Car *c)
{
    if (w->TotalNumCars == WORLD_MAX_CARS)
        world_fail("more than 14 cars for the car table");
    w->CarTable[w->TotalNumCars] = c;
    w->TotalNumCars++;
}

void world_build_car_table(World *w)
{
    Car *c;
    int32_t i;

    w->TotalNumCars = 0;
    w->AICarPos = 0;
    w->CopCarPos = 0;
    w->TrafficCarPos = 0;

    for (c = w->CarList.next; c != CAR_END(w); c = (Car *)c->Link.next)
        if (car_type(c) == DRIVER_TYPE_PLAYER)
            add_car(w, c);
    w->AICarPos = w->TotalNumCars;
    for (c = w->CarList.next; c != CAR_END(w); c = (Car *)c->Link.next)
        if (car_type(c) == DRIVER_TYPE_AI_RACER)
            add_car(w, c);
    w->CopCarPos = w->TotalNumCars;
    for (c = w->CarList.next; c != CAR_END(w); c = (Car *)c->Link.next)
        if (car_type(c) == DRIVER_TYPE_COP
            || car_type(c) == DRIVER_TYPE_SUPER_COP)
            add_car(w, c);
    w->TrafficCarPos = w->TotalNumCars;
    for (c = w->CarList.next; c != CAR_END(w); c = (Car *)c->Link.next)
        if (car_type(c) == DRIVER_TYPE_TRAFFIC_CAR)
            add_car(w, c);

    for (i = 0; i < w->TotalNumCars; i++)
        w->CarTable[i]->CarIndex = (int16_t)i;
    // The listing walks AICarList to its end here and does nothing with
    // it: a loop the compiler kept the shell of.
}

// GetCarByNumber and GetCarByDriverNumber are in world.c, beside the
// replay's pointer snapshot that reads the first.

int32_t world_car_list_check_flip(const Car *a, const Car *b)
{
    return a->State.Position.x <= b->State.Position.x;
}

static int32_t car_list_in_order(bNode *a, bNode *b)
{
    return world_car_list_check_flip((const Car *)(void *)a,
                                     (const Car *)(void *)b);
}

void world_add_traffic_car(World *w, DriverInfo *info)
{
    Car *c;
    Car *tail;

    // A NULL seam places no traffic car, as raceinit.c's NULL
    // AddCopCarToRace places no cop.
    if (gTrafficTeleporterPlaceNewCarFn == NULL)
        return;
    c = gTrafficTeleporterPlaceNewCarFn(w->Teleporter, info);
    if (c == NULL)
        return;
    tail = w->CarList.prev;
    tail->Link.next = &c->Link;
    w->CarList.prev = c;
    c->Link.next = (CarNode *)(void *)&w->CarList;
    c->Link.prev = &tail->Link;
}

// --------------------------------------------------------- the checksums

uint16_t world_calculate_debug_checksum(World *w)
{
    uint32_t s = (uint32_t)WorldTimer;
    int32_t i;

    for (i = 0; i < w->TotalNumCars; i++) {
        Car *c = w->CarTable[i];
        uint32_t v = (uint32_t)car_calculate_debug_checksum(c);

        w->CarPositionTable[i] = c->State.Position;
        s = s * 33u + v;
    }
    // Retail's (0x0014e240) adds the helicopter's x, its Matrix's fourth
    // row read as a word. The image tests &Matrix for NULL, which it never
    // is.
    if (w->Helicopter != NULL) {
        uint32_t x;

        memcpy(&x, &w->Helicopter->Matrix.v3.x, 4);
        s = s + x;
    }
    return (uint16_t)((s >> 16) + s);
}

void world_verify_debug_checksums(World *w)
{
    uint32_t c = world_calculate_debug_checksum(w);
    uint32_t b, e;
    ReplayManager *rm;

    if (Joylog_ReplayingFlag)
        (void)Joylog_GetData(16, 3);
    else
        Joylog_AddData((int32_t)c, 16, 3);

    b = ((c >> 8) + c + (w->WorldRandomSeed & 0xffu)) & 0xffu;
    rm = pReplayManager;
    if (rm->CapturingFlag) {
        ReplayManager_AddData(rm, (int32_t)b, 8, 2);
        return;
    }
    if (!rm->ReplayingFlag)
        return;
    e = (uint32_t)ReplayManager_GetData(rm, 8, 2) & 0xffu;
    if (e == b)
        return;
    WorldVerifyMiss.checksum = c;
    WorldVerifyMiss.seed = w->WorldRandomSeed;
    WorldVerifyMiss.expected = e;
    // Retail's (0x0014e300) marks the replay out of step first, through
    // pReplayManager again: the pause menu and the post-race then leave it
    // alone.
    pReplayManager->OutOfStepFlag = 1;
    if (gRaceCoordinatorPostMessageFn != NULL)
        gRaceCoordinatorPostMessageFn(pRaceCoordinator, RC_SKIP_REPLAY, 0);
}

// ------------------------------------------------------------ the bodies

typedef void (*MoveFn)(void *self, float dt);

void world_do_timestep_move(World *w, float dt)
{
    CollisionBody *moving[WORLD_MAX_MOVING_BODIES];
    CollisionBody *b;
    int32_t n = 0;
    int32_t i;

    (void)w;
    if ((((uint32_t)WorldLoopCounter + 77u) & 127u) == 0
        && gDeleteFarAwaySmokeableCollisionBodiesFn != NULL)
        gDeleteFarAwaySmokeableCollisionBodiesFn();

    for (b = CollisionBodyList.next; b != BODY_END; b = b->Link.next) {
        if (!b->Dynamic)
            continue;
        if (n == WORLD_MAX_MOVING_BODIES)
            world_fail("more than 176 dynamic bodies to move");
        moving[n++] = b;
    }
    for (i = 0; i < n; i++) {
        const VtEntry *e = vt_slot(moving[i]->_vtable, COLLISIONBODY_VT_MOVE);

        ((MoveFn)e->fn)(vt_this(moving[i], e), dt);
    }
    prof_mark(WSP_MOVE);
}

#define CONTACT_END(l) ((Contact *)(void *)(l))

static int32_t is_broken_smokeable(const CollisionBody *b)
{
    return b->Type == SMOKEABLE_COLLISION_BODY
        && ((const Smokeable *)(const void *)b)->BreakingStrength == -1.0f;
}

static int32_t break_smokeable(CollisionBody *b, CollisionBody **pieces,
                               int32_t n)
{
    int32_t k;

    if (gSmokeableBreakFn == NULL)
        world_fail("Smokeable::Break is not ported");
    // Break writes where it is told and returns the count; the array is
    // the image's eight, which it does not check.
    k = gSmokeableBreakFn((Smokeable *)(void *)b,
                          (DynamicCollisionBody **)(void *)&pieces[n]);
    if (k < 0 || n + k > WORLD_MAX_BROKEN_PIECES)
        world_fail("more than 8 bodies after a contact");
    return n + k;
}

static int32_t add_piece(CollisionBody *b, CollisionBody **pieces, int32_t n)
{
    if (is_broken_smokeable(b))
        return break_smokeable(b, pieces, n);
    if (b->Dynamic && b->ActiveCollisionDetection) {
        if (n == WORLD_MAX_BROKEN_PIECES)
            world_fail("more than 8 bodies after a contact");
        pieces[n++] = b;
    }
    return n;
}

void world_do_timestep_collisions(World *w, float dt)
{
    ContactNode list;
    CollisionBody *pieces[WORLD_MAX_BROKEN_PIECES];
    CollisionBodyWitness *wit;
    CollisionBodyWitness *next;
    CollisionBody *b;
    Contact *c;
    struct Collision *col;
    struct Collision *next_col;
    CollisionBody *fb = fall_body(w);
    int32_t round = 0;

    if (fb != NULL) {
        WorldFallTrace.frame = WorldLoopCounter;
        WorldFallTrace.dt = dt;
        WorldFallTrace.zMoved = fall_position(fb)->z;
        WorldFallTrace.vzMoved = fall_velocity(fb)->z;
        WorldFallTrace.dropped = 0;
        WorldFallTrace.resolved = 0;
    }
    collisionbody_maybe_print_all();

    for (wit = CollisionBodyWitnessList.next; wit != WITNESS_END; wit = next) {
        next = wit->Link.next;
        if (cbwitness_has_expired(wit))
            cbwitness_destroy(wit, 3);
    }

    for (b = CollisionBodyList.next; b != BODY_END; b = b->Link.next)
        if (b->Dynamic && b->ActiveCollisionDetection)
            dynamiccollisionbody_maybe_create_witnesses(
                (DynamicCollisionBody *)(void *)b);
    prof_mark(WSP_WITNESSES);
    prof_witnesses();

    list.next = CONTACT_END(&list);
    list.prev = CONTACT_END(&list);
    for (wit = CollisionBodyWitnessList.next; wit != WITNESS_END;
         wit = wit->Link.next)
        cbwitness_test_for_contact(wit, &list);
    prof_mark(WSP_TESTS);
    if (fb != NULL)
        WorldFallTrace.tested = fall_count(&list, fb);

    // Earliest first: resolve the head, drop every other contact either
    // body had, and look again round whatever the resolve left moving.
    while (list.next != CONTACT_END(&list)) {
        CollisionBody *b1;
        CollisionBody *b2;
        WorldFallContact *fc;
        int32_t n;
        int32_t i;

        c = list.next;
        fc = fall_contact_begin(fb, c, round);
        contact_resolve(c);
        fall_contact_end(fb, fc);
        b1 = c->pBody1;
        b2 = c->pBody2;
        if (b1->Dynamic)
            contact_remove_contacts(&list, b1);
        if (b2->Dynamic)
            contact_remove_contacts(&list, b2);

        n = add_piece(b1, pieces, 0);
        n = add_piece(b2, pieces, n);

        for (i = 0; i < n; i++)
            dynamiccollisionbody_maybe_create_witnesses(
                (DynamicCollisionBody *)(void *)pieces[i]);
        for (wit = CollisionBodyWitnessList.next; wit != WITNESS_END;
             wit = wit->Link.next)
            for (i = 0; i < n; i++)
                if (wit->pBody1 == pieces[i] || wit->pBody2 == pieces[i])
                    cbwitness_test_for_contact(wit, &list);

        round++;
        if (round >= WORLD_MAX_CONTACT_ROUNDS)
            break;
    }
    prof_mark(WSP_RESOLVE);
    prof_rounds(round);
    if (fb != NULL) {
        WorldFallTrace.rounds = round;
        if (round == WORLD_MAX_CONTACT_ROUNDS)
            WorldFallTrace.dropped = fall_count(&list, fb);
    }

    // Twenty rounds and still touching: what is left is dropped unresolved.
    if (round == WORLD_MAX_CONTACT_ROUNDS) {
        while ((c = list.next) != CONTACT_END(&list)) {
            c->Link.prev->Link.next = c->Link.next;
            c->Link.next->Link.prev = c->Link.prev;
            contact_destroy(c, 3);
        }
    }

    for (col = w->CollisionList.next;
         col != (struct Collision *)(void *)&w->CollisionList; col = next_col) {
        next_col = col->Link.next;
        if (!collision_update(col, dt))
            collision_end(col);
    }
    prof_mark(WSP_COLLISIONS);
    // ~bTList<Contact>(&list, 2) follows in the image. The list is empty by
    // now either way, and ~bList with flags 2 frees nothing.
}

// ------------------------------------------------------------- the step

static int32_t no_shakes(void)
{
    RCState s = racecoordinator_get_current_state(pRaceCoordinator);

    return s == RCSTATE_INSTANT_REPLAY || s == RCSTATE_POSTRACE
        || s == RCSTATE_AUTO_REPLAY
        || racecoordinator_is_replay_demo_mode(pRaceCoordinator);
}

// The step's thinks and drives go through prof_car, which times them by
// car while the profile is on; the calls below keep the image's names.
#define car_think(c, dt) prof_car(car_think, WorldStepProfile.think, (c), (dt))
#define car_drive(c, dt) prof_car(car_drive, WorldStepProfile.drive, (c), (dt))

void world_do_timestep(World *w, float dt)
{
    int32_t i;

    world_verify_debug_checksums(w);

    for (i = 0; i < WORLD_MAX_PLAYERS; i++) {
        Player *p = PlayerPlayersByNumber[i];

        if (p != NULL) {
            Car *car = p->MyCar;

            w->PlayerPositions[i] = car->State.Position;
            w->PlayerDATs[i] = car->TheTrackPathCoordinate.DistanceAroundTrack;
        } else {
            // The fourth lane is left as it was.
            w->PlayerPositions[i].x = NO_PLAYER;
            w->PlayerPositions[i].y = NO_PLAYER;
            w->PlayerPositions[i].z = NO_PLAYER;
            w->PlayerDATs[i] = NO_PLAYER;
        }
    }

    prof_start();
    if (w->Teleporter != NULL && gTrafficTeleporterDoTimestepFn != NULL)
        gTrafficTeleporterDoTimestepFn(w->Teleporter, dt);
    if (gGlobalCopThinkFn != NULL)
        gGlobalCopThinkFn(dt);
    prof_mark(WSP_COPS);

    // AI racers, traffic, players, cops: the counts are read again after
    // every car.
    for (i = 0; i < w->CopCarPos - w->AICarPos; i++)
        car_think(w->CarTable[w->AICarPos + i], dt);
    for (i = 0; i < w->TotalNumCars - w->TrafficCarPos; i++)
        car_think(w->CarTable[w->TrafficCarPos + i], dt);
    for (i = 0; i < w->AICarPos; i++)
        car_think(w->CarTable[i], dt);
    for (i = 0; i < w->TrafficCarPos - w->CopCarPos; i++)
        car_think(w->CarTable[w->CopCarPos + i], dt);
    prof_mark(WSP_THINK);

    for (i = 0; i < w->AICarPos; i++)
        if (gCarDoWheelForcesFn != NULL)
            gCarDoWheelForcesFn(w->CarTable[i]);
    for (i = 0; i < w->TotalNumCars; i++)
        car_drive(w->CarTable[i], dt);
    prof_mark(WSP_DRIVE);
    if (w->Helicopter != NULL && gChopperFlyFn != NULL)
        gChopperFlyFn(w->Helicopter, dt);
    prof_mark(WSP_CHOPPER);
    for (i = 0; i < w->TotalNumCars; i++)
        car_begin_movement(w->CarTable[i], dt);
    prof_mark(WSP_BEGIN);

    world_do_timestep_move(w, dt);
    world_do_timestep_collisions(w, dt);

    for (i = 0; i < w->TotalNumCars; i++) {
        if (gCarFinishMovementFn == NULL)
            world_fail("Car::FinishMovement is not ported");
        gCarFinishMovementFn(w->CarTable[i], dt);
    }
    prof_mark(WSP_FINISH);
    for (i = 0; i < w->TotalNumCars; i++) {
        Car *car = w->CarTable[i];

        if (world_get_distance_to_closest_player(w, &car->State.Position)
                < 100.0f
            && gCarTriggerEventsFn != NULL)
            gCarTriggerEventsFn(car);
    }

    if (!no_shakes()) {
        for (i = 0; i < w->AICarPos; i++) {
            Car *car = w->CarTable[i];

            if (gCarMaybeCameraShakeFn != NULL)
                gCarMaybeCameraShakeFn(car);
            if (!no_shakes() && gCarMaybeRumbleFn != NULL)
                gCarMaybeRumbleFn(car);
        }
    }
    prof_mark(WSP_EVENTS);

    if (gServiceParticleGroupsFn != NULL)
        gServiceParticleGroupsFn();
    if (gWorldEffectsTweakerCheckFn != NULL)
        gWorldEffectsTweakerCheckFn();
    if (gWorldEffectsDoTimeStepFn != NULL)
        gWorldEffectsDoTimeStepFn(dt);

    for (i = 0; i < w->TotalNumCars; i++) {
        Car *car = w->CarTable[i];
        float d = world_get_distance_to_closest_player(w,
                                                       &car->State.Position);

        if (d < 150.0f && car_should_visual_effects_be_generated(car))
            car_trigger_car_terrain_effects(car, d);
    }
    for (i = 0; i < w->TotalNumCars; i++)
        car_fake_engine_task(w->CarTable[i]);
    prof_mark(WSP_EFFECTS);

    if (gEmProcessAllEventsFn != NULL)
        gEmProcessAllEventsFn();
    blist_sort((bNode *)(void *)&w->CarList, car_list_in_order);
    if (gUpdatePlayersGameStateFn != NULL)
        gUpdatePlayersGameStateFn();
    rain_TimeStep(dt);
    if (gServiceFernFlattenersFn != NULL)
        gServiceFernFlattenersFn();
    if (gServiceTweakerDamageFn != NULL)
        gServiceTweakerDamageFn();
    if (gServiceTrackRouteEditorFn != NULL)
        gServiceTrackRouteEditorFn();
    if (pCurrentRace != NULL && gRaceUpdateFn != NULL)
        gRaceUpdateFn(pCurrentRace);
    prof_end();
}
