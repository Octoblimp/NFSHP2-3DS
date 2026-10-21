// animdriver -- retail's AnimatedDriver.obj. See animdriver.h.

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "animdriver.h"
#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "cartypeinfo.h"
#include "characterinfo.h"
#include "drivecam.h"
#include "eefpu.h"
#include "eview.h"
#include "realtime.h"
#include "replay.h"
#include "scenerycull.h"
#include "stomper.h"
#include "trackflow.h"

int32_t ForceAnimatedDriverLOD = -1;                    // gp-19248

// 0x003111f8. Type is the row; InitAnimatedDriver fills the hashes and
// the frame counts of the rows whose BeginFrame is 0.
DriverAnimationInfo AnimationInfoTable[DRIVER_ANIM_NUM] = {
    {  0, "",                  0,   0,  0,   0, 0, 0, 0 },
    {  1, "DRIVER_ANIM01",     0,  15, 30,   0, 0, 0, 0 },
    {  2, "DRIVER_ANIM01",     0, 231, 30,   0, 0, 0, 1 },
    {  3, "DRIVER_ANIM01",     0,  61, 30,  75, 1, 1, 0 },
    {  4, "DRIVER_ANIM01",     0, 111, 20, 121, 1, 1, 1 },
    {  5, "DRIVER_ANIM01",     0,  91, 20, 101, 1, 1, 1 },
    {  6, "DRIVER_ANIM01",     0, 211, 20,   0, 2, 1, 0 },
    {  7, "DRIVER_ANIM01",     0, 131, 20,   0, 3, 1, 0 },
    {  8, "DRIVER_ANIM01",     0, 151, 20,   0, 3, 1, 0 },
    {  9, "DRIVER_ANIM01",     0, 171, 20,   0, 3, 1, 0 },
    { 10, "DRIVER_ANIM01",     0, 191, 20,   0, 3, 1, 0 },
    { 11, "DRIVER_SHIFT01",    0,   1, 30,   0, 1, 1, 0 },
    { 12, "Driver_PreRaceG02", 0,   0,  0,   0, 0, 0, 0 },
    { 13, "Driver_PreRaceG14", 0,   0,  0,   0, 0, 0, 0 },
};

// 0x003113f0.
static const char *const DriverAnimationTypeNames[DRIVER_ANIM_NUM] = {
    "NONE", "STEERING", "IDLE", "DRIVING_BACKWARDS",
    "LOOKING_BACKWARDS_LEFT", "LOOKING_BACKWARDS_RIGHT", "COLLISION_LIGHT",
    "COLLISION_FRONT", "COLLISION_RIGHT", "COLLISION_LEFT", "COLLISION_BACK",
    "GEAR_CHANGE", "PRERACEG02", "PRERACEG14",
};

// 0x00311100: added to the steering's frame, one a tick of WorldTime.
static const float SteeringWiggleTable[62] = {
    0.0f, 0.1f, 0.2f, 0.3f, 0.5f, 0.7f, 0.9f, 1.1f, 1.2f, 1.3f,
    1.35f, 1.37f, 1.3f, 1.26f, 1.1f, 1.0f, 0.8f, 0.7f, 0.7f, 0.75f,
    0.8f, 0.9f, 0.8f, 0.6f, 0.5f, 0.3f, 0.1f, -0.1f, -0.2f, -0.3f,
    -0.4f, -0.6f, -0.7f, -0.75f, -0.8f, -0.85f, -0.84f, -0.7f, -0.6f, -0.6f,
    -0.5f, -0.4f, -0.2f, -0.1f, 0.1f, -0.1f, -0.2f, -0.3f, -0.4f, -0.6f,
    -0.7f, -0.75f, -0.8f, -0.85f, -0.84f, -0.7f, -0.6f, -0.6f, -0.5f, -0.4f,
    -0.2f, -0.1f,
};

typedef struct DriverAnimPair {
    int32_t Type;
    int32_t CarType;
} DriverAnimPair;

// 0x00311428: by car type.
static const DriverAnimPair BlackballedForCar[21] = {
    {  8, 23 }, { 12, 23 }, {  8, 24 }, { 12, 24 }, {  8, 47 }, {  8, 48 },
    {  8,  2 }, {  8,  3 }, {  8, 21 }, { 11, 13 }, { 11, 14 }, { 11, 15 },
    { 11, 16 }, {  3, 13 }, {  3, 14 }, {  3, 15 }, {  3, 16 }, { 11,  7 },
    { 11,  8 }, { 11,  9 }, { 11, 10 },
};

// 0x003114d0: under a roof, outside view mode 1 (only the type is read).
static const DriverAnimPair BlackballedUnderRoof[2] = {
    { 11, 0 }, { 2, 0 },
};

// 0x003114e0: for a cop.
static const DriverAnimPair BlackballedForCop[8] = {
    { 8, 32 }, { 7, 32 }, { 8, 4 }, { 7, 4 }, { 10, 4 }, { 8, 33 },
    { 7, 33 }, { 10, 33 },
};

// gp-19216: the bones the gear change moves.
static const int8_t ShiftBones[3] = { 30, 31, 32 };

// The bone tree's size, and the steering solid's name (0x2bb7f510).
#define DRIVER_NUM_BONES 42
#define DRIVER_STEERING_SOLID_HASH 0x2bb7f510u

const char *animdriver_type_name(int32_t type)
{
    return DriverAnimationTypeNames[type];
}

int32_t animdriver_blackballed(int32_t type, int32_t car_type,
                               const struct CharacterInfo *ci)
{
    int32_t i;

    for (i = 0; i < 21; i++)
        if (BlackballedForCar[i].Type == type
            && BlackballedForCar[i].CarType == car_type)
            return 1;
    {
        const CarTypeInfo *cti = &CarTypeInfoArray[car_type];

        if (eGetCurrentViewMode() != 1 && cti->OpenTop == 0)
            for (i = 0; i < 2; i++)
                if (BlackballedUnderRoof[i].Type == type)
                    return 1;
    }
    if (ci == NULL)
        return 0;
    if (ci->BodyTypeName[0] != 'C' || ci->BodyTypeName[1] != 'o')
        return 0;
    for (i = 0; i < 8; i++)
        if (BlackballedForCop[i].Type == type
            && BlackballedForCop[i].CarType == car_type)
            return 1;
    return 0;
}

// -------------------------------------------------------- AnimationPlayer

void animplayer_begin(AnimationPlayer *p, int32_t type, int32_t delay)
{
    DriverAnimationInfo *info;

    if ((uint32_t)type >= DRIVER_ANIM_NUM)
        return;
    p->StartTime = WorldTime + delay;
    info = &AnimationInfoTable[type];
    p->pAnimationInfo = info;
    p->EndTime = p->StartTime + info->NumFrames * 2;
    p->PauseFrameNumber = info->PauseFrameNumber;
    if (p->PauseFrameNumber != 0)
        p->EndTime = p->StartTime + 100000;
}

void animplayer_release_paused_frame(AnimationPlayer *p)
{
    int32_t f = animplayer_get_frame_number(p);
    DriverAnimationInfo *info = p->pAnimationInfo;

    p->EndTime = WorldTime + (info->BeginFrame + info->NumFrames - f) * 2;
    p->PauseFrameNumber = 0;
    p->StartTime = p->EndTime - info->NumFrames * 2;
}

void animplayer_release(AnimationPlayer *p)
{
    int32_t now = WorldTime;
    int32_t active = 0;

    if (now < p->EndTime)
        active = !(now < p->StartTime);
    if (!active) {
        animplayer_cancel(p);
        return;
    }
    if (p->EndTime - now > 0 && p->PauseFrameNumber != 0)
        animplayer_release_paused_frame(p);
}

int32_t animplayer_get_frame_number(const AnimationPlayer *p)
{
    const DriverAnimationInfo *info = p->pAnimationInfo;
    int32_t f = info->BeginFrame + (WorldTime - p->StartTime) / 2;

    if (p->PauseFrameNumber == -1) {
        if (f < info->NumFrames)
            return f;
        do
            f -= info->NumFrames;
        while (!(f < info->NumFrames));
        return f;
    }
    if (p->PauseFrameNumber != 0 && p->PauseFrameNumber < f)
        f = p->PauseFrameNumber;
    return f;
}

void animplayer_cancel(AnimationPlayer *p)
{
    animplayer_begin(p, DRIVER_ANIM_NONE, 0);
}

// The player is playing: begun, and not yet ended.
static int32_t animplayer_is_active(const AnimationPlayer *p)
{
    int32_t now = WorldTime;

    return now < p->EndTime && !(now < p->StartTime);
}

// ---------------------------------------------------- the global set-up

void InitAnimatedDriver(void)
{
    int32_t t;

    for (t = 1; t < DRIVER_ANIM_NUM; t++) {
        DriverAnimationInfo *info = &AnimationInfoTable[t];
        eAnimationSolid *solid;
        char name[32];
        int32_t i;

        // bToUpper (0x00253790) a character at a time, up to 30.
        memset(name, 0, sizeof name);
        for (i = 0; i < 30; i++) {
            int32_t c = (int8_t)info->SolidName[i];

            if ((uint32_t)(c - 97) < 26u)
                c &= 0x5f;
            name[i] = (char)c;
            if ((int8_t)c == 0)
                break;
        }
        info->SolidNameHash = bchunk_hash(name);
        solid = eFindAnimationSolid(info->SolidNameHash);
        if (solid == NULL) {
            info->NumFrames = 0;
            continue;
        }
        if (info->BeginFrame == 0)
            info->NumFrames = solid->NumFrames;
        if (AnimatedDriverNeedsFixup && info->CombineWithSteering) {
            int32_t f;

            for (f = info->BeginFrame;
                 f < info->BeginFrame + info->NumFrames; f++) {
                int32_t n;

                for (n = 0; n < DRIVER_NUM_BONES; n++) {
                    bQuaternion q30, qf, inv, r;

                    eanimsolid_get_rotation(solid, &q30, n, 30.0f);
                    eanimsolid_get_rotation(solid, &qf, n, (float)f);
                    bConjugate(&inv, &q30);
                    bMult(&r, &inv, &qf);
                    bNormalize(&r, &r);
                    eanimsolid_set_rotation(solid, &r, n, (float)f);
                }
            }
        }
    }
    AnimatedDriverNeedsFixup = 0;
}

void CloseAnimatedDriver(void)
{
}

// --------------------------------------------------------- AnimatedDriver

static void animdriver_clear(AnimatedDriver *d)
{
    int32_t i;

    d->SteeringWiggleNumber = 0;
    d->DisableRenderingFlag = 0;
    d->LookingBackwardsFlag = 0;
    d->DrivingBackwardsFlag = 0;
    d->CurrentLookingBackwardsType = 0;
    for (i = 0; i < 3; i++) {
        d->pAnimations[i] = NULL;
        d->pModels[i] = NULL;
    }
}

AnimatedDriver *animdriver_construct_character(AnimatedDriver *d,
                                               struct CharacterInfo *ci)
{
    animplayer_begin(&d->AnimationPlayers[0], DRIVER_ANIM_NONE, 0);
    animplayer_begin(&d->AnimationPlayers[1], DRIVER_ANIM_NONE, 0);
    d->pCharacterInfo = ci;
    d->pCar = NULL;
    animdriver_clear(d);
    animdriver_initialize_artwork(d);
    animdriver_setup_steering_frame(d);
    return d;
}

AnimatedDriver *animdriver_construct(AnimatedDriver *d, struct Car *car,
                                     const char *name)
{
    (void)name;
    animplayer_begin(&d->AnimationPlayers[0], DRIVER_ANIM_NONE, 0);
    animplayer_begin(&d->AnimationPlayers[1], DRIVER_ANIM_NONE, 0);
    d->pCar = car;
    d->pCharacterInfo = car->MyDriver != NULL
                        ? car->MyDriver->pCharacterInfo : NULL;
    animdriver_clear(d);
    animdriver_initialize_artwork(d);
    animdriver_setup_steering_frame(d);
    return d;
}

void animdriver_destroy(AnimatedDriver *d, int32_t flags)
{
    int32_t i;

    for (i = 0; i < 3; i++) {
        if (d->pAnimations[i] != NULL)
            eanim_destroy(d->pAnimations[i], 3);
        if (d->pModels[i] != NULL)
            emodel_delete(d->pModels[i], 3);
    }
    bFree(d->pSteeringFrame);
    if (flags & 1)
        bFree(d);
}

void animdriver_setup_steering_frame(AnimatedDriver *d)
{
    BSpline *s = (BSpline *)bMalloc(48, "..\\indep\\src\\animateddriver.cpp",
                                    520, 16);

    // Retail leaves the coefficients and the time as bMalloc has them: a
    // seek at state 2 sets them before it reads them, and at 0 reads
    // neither.
    s->val = 30.0f;
    s->dval = 0.0f;
    s->valDesired = 30.0f;
    s->dvalDesired = 0.0f;
    s->duration = 0.1f;
    s->arrivalThreshold = 1.0f;
    s->state = 0;
    s->flags = 1;
    d->pSteeringFrame = s;
}

void animdriver_initialize_artwork(AnimatedDriver *d)
{
    CharacterInfo *ci;
    BodyTypeInfo *bti;
    int32_t instance = 0;
    int32_t j;

    for (j = 0; j < 3; j++) {
        if (d->pAnimations[j] != NULL)
            eanim_uninit(d->pAnimations[j]);
        if (d->pModels[j] != NULL)
            emodel_uninit(d->pModels[j]);
    }
    ci = d->pCharacterInfo;
    if (ci == NULL)
        return;
    bti = get_body_type_info(ci->BodyTypeName);
    if (bti == NULL)
        return;
    d->SkinReplacementTextureTable[0].OldNameHash = bti->MappedBodyHash;
    d->SkinReplacementTextureTable[0].NewNameHash =
        bti->BodySkinHash[ci->BodySkinNumber];
    d->SkinReplacementTextureTable[1].OldNameHash = bti->MappedHeadHash;
    d->SkinReplacementTextureTable[1].NewNameHash =
        bti->HeadSkinHash[ci->HeadSkinNumber];

    for (j = 0; j < 3; j++) {
        uint32_t hash = j == 1 ? bti->ObjectNameHashB
                      : j == 2 ? bti->ObjectNameHashC : bti->ObjectNameHashA;
        eModel tmp;

        if (hash == 0)
            continue;
        memset(&tmp, 0, sizeof tmp);
        emodel_init(&tmp, hash);
        if (tmp.Solid != NULL) {
            eAnimationTree *tree = emodel_get_animation_tree(&tmp);

            if (tree != NULL && tree->NumNodes > 0) {
                if (d->pAnimations[j] == NULL)
                    d->pAnimations[j] = eanim_construct(
                        (eAnimation *)bMalloc(80, "eAnimation", 0, 16));
                eanim_init(d->pAnimations[j], hash);
                emodel_attach_replacement_texture_table(
                    &d->pAnimations[j]->Model, d->SkinReplacementTextureTable,
                    2, instance++);
            } else {
                if (d->pModels[j] == NULL) {
                    eModel *m = (eModel *)bSlotOMalloc(eModelSlotPool);

                    m->NameHash = 0;
                    m->Solid = NULL;
                    d->pModels[j] = m;
                }
                emodel_init(d->pModels[j], hash);
                emodel_attach_replacement_texture_table(
                    d->pModels[j], d->SkinReplacementTextureTable, 2,
                    instance++);
            }
        }
        emodel_delete(&tmp, 2);
    }
    d->ShiftAnimationNameHash = bchunk_hash("DRIVER_SHIFT01");
}

void animdriver_do_snapshot(AnimatedDriver *d, struct ReplaySnapshot *s)
{
    ReplaySnapshot_BeginNamedSection(s, "AnimatedDriver");
    if (s->RestoringSnapshotFlag)
        animdriver_cancel_all(d);
    ReplaySnapshot_MoveChar(s, &d->LookingBackwardsFlag, 1);
    ReplaySnapshot_MoveChar(s, &d->DrivingBackwardsFlag, 1);
    ReplaySnapshot_EndSection(s);
}

void animdriver_render(AnimatedDriver *d, bMatrix4 *m,
                       struct eLightContext *light, uint32_t flags,
                       int32_t lod)
{
    int32_t l = ForceAnimatedDriverLOD < 0 ? lod : ForceAnimatedDriverLOD;

    if (OverrideAnimatedDriverLOD != 0 && !(l < 2))
        l = 1;
    if (d->pAnimations[l] != NULL) {
        bQuaternion q[DRIVER_NUM_BONES];
        bVector3 t;

        animdriver_build_quaternion_table(d, d->pAnimations[l], q, &t);
        eanim_render_posed(d->pAnimations[l], m, &t, q, light, flags);
    } else if (d->pModels[l] != NULL) {
        if (gEModelRenderFn != NULL)
            gEModelRenderFn(d->pModels[l], m, light, flags);
    }
}

void animdriver_cancel_all(AnimatedDriver *d)
{
    animplayer_cancel(&d->AnimationPlayers[0]);
    animplayer_cancel(&d->AnimationPlayers[1]);
}

void animdriver_release_all(AnimatedDriver *d)
{
    animplayer_release(&d->AnimationPlayers[0]);
    animplayer_release(&d->AnimationPlayers[1]);
}

void animdriver_begin_gear_change(AnimatedDriver *d)
{
    animdriver_queue_animation(d, DRIVER_ANIM_GEAR_CHANGE);
}

void animdriver_begin_driving_backwards(AnimatedDriver *d)
{
    if (!d->DrivingBackwardsFlag) {
        d->DrivingBackwardsFlag = 1;
        animdriver_handle_driving_backwards(d);
    }
}

void animdriver_end_driving_backwards(AnimatedDriver *d)
{
    if (d->DrivingBackwardsFlag) {
        d->DrivingBackwardsFlag = 0;
        animdriver_release_animation(d, DRIVER_ANIM_DRIVING_BACKWARDS);
    }
}

void animdriver_handle_driving_backwards(AnimatedDriver *d)
{
    if (animdriver_find_animation(d, DRIVER_ANIM_DRIVING_BACKWARDS) == NULL)
        animdriver_queue_animation(d, DRIVER_ANIM_DRIVING_BACKWARDS);
}

void animdriver_begin_looking_backwards(AnimatedDriver *d)
{
    if (!d->LookingBackwardsFlag) {
        d->LookingBackwardsFlag = 1;
        d->CurrentLookingBackwardsType = DRIVER_ANIM_LOOKING_BACKWARDS_RIGHT;
        animdriver_handle_looking_backwards(d);
    }
}

void animdriver_end_looking_backwards(AnimatedDriver *d)
{
    if (d->LookingBackwardsFlag) {
        d->LookingBackwardsFlag = 0;
        animdriver_release_animation(d, DRIVER_ANIM_LOOKING_BACKWARDS_RIGHT);
        animdriver_release_animation(d, DRIVER_ANIM_LOOKING_BACKWARDS_LEFT);
    }
}

void animdriver_handle_looking_backwards(AnimatedDriver *d)
{
    int32_t s = d->CurrentLookingBackwardsType;

    if (d->pCar != NULL) {
        int32_t is_cop;
        Car *other = get_lookback_car(d->pCar, &is_cop);

        if (other != NULL) {
            uint16_t a = calculate_lookback_angle(d->pCar, other,
                                                  &d->pCar->State.BodyMatrix);

            if (a == 0)
                s = 0;
            else if (a == 0x8000 || a == 0x4000)
                s = DRIVER_ANIM_LOOKING_BACKWARDS_RIGHT;
            else if (a == 0xc000)
                s = DRIVER_ANIM_LOOKING_BACKWARDS_LEFT;
        } else {
            uint32_t st = car_get_steering(d->pCar);

            // 10, 180 and 350 degrees, as BAMs.
            if ((uint32_t)(0xa0000 / 360) < st
                && st < (uint32_t)(0xb40000 / 360))
                s = DRIVER_ANIM_LOOKING_BACKWARDS_LEFT;
            else if ((uint32_t)(0xb40000 / 360) < st
                     && st < (uint32_t)(0x15e0000 / 360))
                s = DRIVER_ANIM_LOOKING_BACKWARDS_RIGHT;
            else
                s = d->CurrentLookingBackwardsType;
        }
    }
    if (s != DRIVER_ANIM_LOOKING_BACKWARDS_LEFT)
        animdriver_release_animation(d, DRIVER_ANIM_LOOKING_BACKWARDS_LEFT);
    if (s != DRIVER_ANIM_LOOKING_BACKWARDS_RIGHT)
        animdriver_release_animation(d, DRIVER_ANIM_LOOKING_BACKWARDS_RIGHT);
    if (s != 0 && animdriver_find_animation(d, s) == NULL)
        animdriver_queue_animation(d, s);
    d->CurrentLookingBackwardsType = s;
}

void animdriver_begin_collision(AnimatedDriver *d, int32_t type,
                                int32_t strength)
{
    int32_t i;

    for (i = 0; i < 2; i++) {
        const AnimationPlayer *p = &d->AnimationPlayers[i];

        if (animplayer_is_active(p)) {
            int32_t allow = p->pAnimationInfo->AllowCollisionInterruption;

            if (allow == 0 || !(allow < strength))
                return;
        }
    }
    animdriver_cancel_all(d);
    animdriver_queue_animation(
        d, animdriver_blackballed(type, d->pCar->pRideInfo->Type,
                                  d->pCharacterInfo)
           ? DRIVER_ANIM_COLLISION_LIGHT : type);
}

int32_t animdriver_queue_animation(AnimatedDriver *d, int32_t type)
{
    int32_t now, best = 0, idx = -1, i;

    if (d->pCar != NULL
        && animdriver_blackballed(type, d->pCar->pRideInfo->Type,
                                  d->pCharacterInfo))
        return 0;
    now = WorldTime;
    for (i = 0; i < 2; i++) {
        int32_t rem = d->AnimationPlayers[i].EndTime - now;

        if (rem <= 0)
            idx = i;
        else if (!(rem < 10001))
            return 0;
        else if (best < rem)
            best = rem;
    }
    if (idx < 0)
        return 0;
    animplayer_begin(&d->AnimationPlayers[idx], type, best);
    return 1;
}

int32_t animdriver_get_length_of_queued(AnimatedDriver *d)
{
    int32_t best = 0, i;

    for (i = 0; i < 2; i++) {
        int32_t rem = d->AnimationPlayers[i].EndTime - WorldTime;

        if (best < rem)
            best = rem;
    }
    return best;
}

AnimationPlayer *animdriver_find_animation(AnimatedDriver *d, int32_t type)
{
    int32_t i;

    for (i = 0; i < 2; i++) {
        AnimationPlayer *p = &d->AnimationPlayers[i];

        if (p->pAnimationInfo->Type == type && p->EndTime - WorldTime > 0)
            return p;
    }
    return NULL;
}

void animdriver_release_animation(AnimatedDriver *d, int32_t type)
{
    int32_t i;

    for (i = 0; i < 2; i++)
        if (d->AnimationPlayers[i].pAnimationInfo->Type == type)
            animplayer_release(&d->AnimationPlayers[i]);
}

int32_t animdriver_calculate_steering_frame_number(AnimatedDriver *d)
{
    float s = 0.0f, f;
    BSpline *spline;

    if (d->pCar != NULL && d->pCar->pCarDriver != NULL)
        s = (float)(int32_t)car_get_steering(d->pCar) * 0x1p-16f;
    if (s < 0.5f)
        f = s * 150.0f + 30.0f;
    else
        f = 30.0f - (1.0f - s) * 150.0f;
    f = f + SteeringWiggleTable[((uint32_t)WorldTime
                                 - (uint32_t)d->SteeringWiggleNumber) % 62u];
    if (45.0f < f)
        f = 45.0f;
    if (f < 15.0f)
        f = 15.0f;
    spline = d->pSteeringFrame;
    spline->valDesired = f;
    if (!(f == spline->val))
        spline->state = 2;
    return ee_trunc_w(spline->val);
}

void animdriver_queue_random_animations(AnimatedDriver *d, int32_t first,
                                        int32_t last, int32_t count)
{
    int32_t range = last - first + 1;
    int32_t prev = -1, queued = 0, tries;

    if (range <= 0 || count <= 0)
        return;
    // Retail draws on bDefaultSeed; the camera coordinator calls this on
    // the console whose view it is, so the port's draws are bViewSeed's
    // (bmath.h), which a lockstep race keeps off the world's.
    for (tries = 1; ; tries++) {
        int32_t t = first + bRandomI(range, bViewSeed);

        if (t != prev && AnimationInfoTable[t].NumFrames != 0
            && !(d->pCar != NULL
                 && animdriver_blackballed(t, d->pCar->pCarTypeInfo->Type,
                                           d->pCharacterInfo))) {
            animdriver_queue_animation(d, t);
            prev = t;
            queued++;
        }
        if (!(queued < count) || !(tries < 1001))
            break;
    }
}

void animdriver_build_quaternion_table(AnimatedDriver *d, eAnimation *a,
                                       bQuaternion *q, bVector3 *t)
{
    AnimationPlayer *p = NULL;
    DriverAnimationInfo *info;
    eAnimationSolid *solid;
    float w;
    int32_t fr, f, i;

    if (d->LookingBackwardsFlag)
        animdriver_handle_looking_backwards(d);
    if (d->DrivingBackwardsFlag)
        animdriver_handle_driving_backwards(d);
    for (i = 0; i < 2; i++)
        if (animplayer_is_active(&d->AnimationPlayers[i])) {
            p = &d->AnimationPlayers[i];
            break;
        }

    d->pSteeringFrame->duration = 0.1f;
    bspline_seek(d->pSteeringFrame, WorldTimeElapsed);
    fr = animdriver_calculate_steering_frame_number(d);
    solid = eanim_get_animation_solid(a, DRIVER_STEERING_SOLID_HASH);
    if (solid != NULL) {
        eanimsolid_get_rotations(solid, q, (float)fr);
        eanimsolid_get_translation(solid, t, (float)fr);
    } else {
        t->z = 0.0f;
        t->x = 0.0f;
        t->y = 0.0f;
    }

    if (p == NULL) {
        if (WorldLoopCounter % 120 == 0)
            animdriver_queue_animation(d, DRIVER_ANIM_IDLE);
        return;
    }

    w = 1.0f;
    f = animplayer_get_frame_number(p);
    info = p->pAnimationInfo;
    if (info->BlendWithSteering) {
        int32_t in = f - info->BeginFrame;

        if (in < 5) {
            w = 0.2f * (float)(in + 1);
        } else {
            int32_t out = info->BeginFrame + info->NumFrames - f;

            if (out < 5)
                w = (float)out * 0.2f;
        }
    }

    if (info->Type == DRIVER_ANIM_GEAR_CHANGE) {
        solid = eanim_get_animation_solid(a, d->ShiftAnimationNameHash);
        if (solid == NULL)
            return;
        for (i = 0; i < 3; i++) {
            bQuaternion r;
            int32_t b = ShiftBones[i];

            eanimsolid_get_rotation(solid, &r, b, (float)f);
            bSlerp(&q[b], &q[b], &r, w);
        }
        return;
    }
    if (w == 0.0f)
        return;
    if (info->CombineWithSteering) {
        // Retail reads the solid unchecked; a port guard for a bundle
        // without DRIVER_ANIM01, where a looking-back pause still plays.
        solid = eanim_get_animation_solid(a, info->SolidNameHash);
        if (solid == NULL)
            return;
        for (i = 0; i < DRIVER_NUM_BONES; i++) {
            bQuaternion r;

            eanimsolid_get_rotation(solid, &r, i, (float)f);
            bMult(&q[i], &q[i], &r);
        }
    } else if (w == 1.0f) {
        solid = eanim_get_animation_solid(a, info->SolidNameHash);
        if (solid != NULL)
            eanimsolid_get_rotations(solid, q, (float)f);
    } else {
        solid = eanim_get_animation_solid(a, info->SolidNameHash);
        if (solid == NULL)
            return;
        for (i = 0; i < DRIVER_NUM_BONES; i++) {
            bQuaternion r;

            eanimsolid_get_rotation(solid, &r, i, (float)f);
            bSlerp(&q[i], &q[i], &r, w);
        }
    }
}

void animdriver_begin_a_pre_race_animation(AnimatedDriver *d)
{
    animdriver_queue_random_animations(d, DRIVER_ANIM_PRERACEG02,
                                       DRIVER_ANIM_PRERACEG14, 2);
}

void car_assign_animated_driver(struct Car *c, const char *name)
{
    if (c->pCarTypeInfo->UsageType != 2)
        c->pAnimatedDriver = animdriver_construct(
            (AnimatedDriver *)bMalloc(144, "..\\indep\\src\\car.cpp", 1887,
                                      16),
            c, name);
}

void car_unassign_animated_driver(struct Car *c)
{
    if (c->pAnimatedDriver != NULL) {
        animdriver_destroy(c->pAnimatedDriver, 3);
        c->pAnimatedDriver = NULL;
    }
}
