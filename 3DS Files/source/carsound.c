#include "carsound.h"

#include <stddef.h>
#include <string.h>

#include "bmem.h"
#include "bvector.h"
#include "car.h"
#include "carinit.h"
#include "cartypeinfo.h"
#include "collisionbody.h"
#include "eefpu.h"
#include "player.h"
#include "playerzone.h"
#include "race.h"
#include "realtime.h"
#include "sound.h"
#include "terraintype.h"
#include "topology.h"
#include "vtable.h"
#include "world.h"

// ------------------------------------------------------------ the globals

int32_t CarSoundEnabled = 1;                    // gp-20456
int32_t CarDamageSoundEnabled = 1;              // gp-20460
int32_t RoadNoiseEnabled = 1;                   // gp-16248

// _GLOBAL_$I$CarSoundMultiPlayerAzimuth (0x0018f0f8) fills both, and
// CarSoundMultiPlayerAzimuth (sound3d.c's) and ReflectionAzimuth.
Sound3dEnvelope BasePlayerCarSoundEnvelope = {
    1.3f, 260.0f, 1.0f / 260.0f                 // gp-29980, 0x43820000, gp-29984
};
Sound3dEnvelope BaseAICarSoundEnvelope = {
    1.3f, 130.0f, 1.0f / 130.0f                 // gp-29980, 0x43020000, gp-29976
};

BaseCarSound *ClosestCarSounds[CARSOUND_MAX_CLOSEST];   // 0x003100c0
int32_t MaxActiveCarSounds = 3;                 // gp-20400
int32_t NumClosestCarSounds;                    // gp-20396

CarSoundCreateFn     gCreatePlayerEngineFn;
CarSoundCreateFn     gCreateAIEngineFn;
CarSoundCreateTireFn gCreatePlayerTireFn;
CarSoundCreateFn     gCreateAITireFn;
void (*gTireSoundTriggerBlowOutFn)(Sound3d *tire);
void (*gTireSoundScaleRoadNoiseFn)(Sound3d *tire, float f);

// POVVolumeTable (0x00310090): per drive camera POV, the engine's, the
// wind's and the tyres' volumes -- GetPOVVolume reads type 1 from the third
// column and type 2 from the second.
static const float POVVolumeTable[4][3] = {
    { 0.8f,  1.0f,  0.75f },
    { 0.9f,  0.9f,  0.85f },
    { 1.0f,  0.75f, 1.0f  },
    { 1.25f, 0.4f,  0.9f  },
};

static uint16_t ReflectionAzimuth = 16384;      // gp-13392, a quarter turn
static int32_t  HornCounter;                    // gp-20436
static int32_t  SirenCounter;                   // gp-20440

typedef void (*VtDestroyFn)(void *self, int32_t flags);
typedef void (*VtActivateFn)(void *self, int32_t on);
typedef void (*VtUpdateFn)(void *self, float volume, uint16_t azimuth,
                           float pitch);
typedef void (*VtMuteFn)(void *self, int32_t on);
typedef void (*VtVoidFn)(void *self);
typedef void (*VtCamRelativeFn)(void *self, const bVector3 *pos);
typedef bVector3 *(*VtVectorFn)(void *self);
typedef int32_t (*VtTerrainFn)(void *self);

// The calls through a Sound3d's table, `s` the Sound3d (every class here
// has it at 0, so every delta is 0).
static void s3d_destroy(void *s, int32_t flags)
{
    const VtEntry *e = vt_slot(((Sound3d *)s)->_vtable, SOUND3D_VT_DESTROY);

    ((VtDestroyFn)e->fn)(vt_this(s, e), flags);
}

static void s3d_activate(void *s, int32_t on)
{
    const VtEntry *e = vt_slot(((Sound3d *)s)->_vtable, SOUND3D_VT_ACTIVATE);

    ((VtActivateFn)e->fn)(vt_this(s, e), on);
}

static void s3d_update(void *s, float volume, uint16_t azimuth, float pitch)
{
    const VtEntry *e = vt_slot(((Sound3d *)s)->_vtable, SOUND3D_VT_UPDATE);

    ((VtUpdateFn)e->fn)(vt_this(s, e), volume, azimuth, pitch);
}

static void s3d_mute(void *s, int32_t on)
{
    const VtEntry *e = vt_slot(((Sound3d *)s)->_vtable, SOUND3D_VT_MUTE);

    ((VtMuteFn)e->fn)(vt_this(s, e), on);
}

// smooth<float> (0x00136630), sound.c's: `a` a step of at most `step`
// towards `b`.
static float smooth(float a, float b, float step)
{
    float up = a + step;
    float down;

    if (up < b)
        return up;
    down = a - step;
    if (b < down)
        return down;
    return b;
}

// The in-game region's sample `name`.
static BSample *in_game_sample(const char *name)
{
    return sound_get_in_game_sample(sound_get(), name);
}

// ------------------------------------------------------------ the module

float carsound_get_pov_volume(Car *c, int32_t type)
{
    int32_t pov = c->pPlayer != NULL
                  ? c->pPlayer->PlayerSettings.DriveCameraPOVIndex : 0;

    switch (type) {
    case 0:
        return POVVolumeTable[pov][0];
    case 1:
        return POVVolumeTable[pov][2];
    case 2:
        return POVVolumeTable[pov][1];
    }
    return 1.0f;
}

BaseCarSound *carsound_create_player(Car *c)
{
    BasePlayerCarSound *s = bMalloc(sizeof(BasePlayerCarSound),
                                    "PlayerCarSound", 0, 16);

    baseplayercarsound_construct(s, c);
    return &s->Base;
}

BaseCarSound *carsound_create_ai(Car *c)
{
    BaseAICarSound *s = bMalloc(sizeof(BaseAICarSound), "AICarSound", 0, 16);

    baseaicarsound_construct(s, c);
    return &s->Base;
}

// The cop's is the AI's: the siren comes from the car's usage.
BaseCarSound *carsound_create_ai_cop(Car *c)
{
    BaseAICarSound *s = bMalloc(sizeof(BaseAICarSound), "AICarSound", 0, 16);

    baseaicarsound_construct(s, c);
    return &s->Base;
}

void carsound_delete(BaseCarSound *s, int32_t flags)
{
    s3d_destroy(s, flags);
}

struct TopologyCoordinate *carsound_get_reverb_topology_coordinate(
    BaseCarSound *s)
{
    return ((BasePlayerCarSound *)s)->ReverbTopologyCoordinate;
}

void carsound_maybe_insert(BaseCarSound *s)
{
    int32_t i;

    if (!basecarsound_in_sound_sphere(s))
        return;
    for (i = 0; i < MaxActiveCarSounds; i++) {
        if (ClosestCarSounds[i] == NULL) {
            ClosestCarSounds[i] = s;
            NumClosestCarSounds++;
            return;
        }
    }
    // Full: the first one further off than this gives way to it.
    for (i = 0; i < MaxActiveCarSounds; i++) {
        if (s->Sound.SndToCameraDistance
            < ClosestCarSounds[i]->Sound.SndToCameraDistance) {
            ClosestCarSounds[i] = s;
            return;
        }
    }
}

void carsound_maybe_activate(BaseCarSound *s)
{
    int32_t found = 0;
    int32_t i;

    for (i = 0; i < MaxActiveCarSounds; i++) {
        if (ClosestCarSounds[i] == s) {
            found = 1;
            break;
        }
    }
    s3d_activate(s, found);
}

void carsound_update_car_sounds(void)
{
    Car *c;
    int32_t i;

    if (pCurrentWorld == NULL)
        return;
    MaxActiveCarSounds = TheRaceParameters.NumPlayerCars > 1 ? 3 : 6;

    for (c = (Car *)pCurrentWorld->CarList.next;
         c != (Car *)&pCurrentWorld->CarList; c = (Car *)c->Link.next)
        car_update_sound(c);

    for (i = 0; i < MaxActiveCarSounds; i++)
        ClosestCarSounds[i] = NULL;
    NumClosestCarSounds = 0;

    // Retail reads pBaseCarSound without a test; a car the port made
    // without sound has none.
    for (c = (Car *)pCurrentWorld->CarList.next;
         c != (Car *)&pCurrentWorld->CarList; c = (Car *)c->Link.next)
        if (c->MyDriver->TheDriverType != DRIVER_TYPE_PLAYER
            && c->pBaseCarSound != NULL)
            carsound_maybe_insert(c->pBaseCarSound);
    for (c = (Car *)pCurrentWorld->CarList.next;
         c != (Car *)&pCurrentWorld->CarList; c = (Car *)c->Link.next)
        if (c->MyDriver->TheDriverType != DRIVER_TYPE_PLAYER
            && c->pBaseCarSound != NULL)
            carsound_maybe_activate(c->pBaseCarSound);
}

// ----------------------------------------------------------- BaseCarSound

void basecarsound_construct(BaseCarSound *s, Car *c)
{
    int32_t i;

    sound3d_construct(&s->Sound);
    s->pCar = c;
    s->SplashLeft = 0;
    s->SplashRight = 0;
    s->SplashLeftTimer = 0;
    s->SplashRightTimer = 0;
    s->Sound._vtable = BASECARSOUND_VTABLE;
    for (i = 0; i < 3; i++)
        bsample_set_category(basecarsound_get_splash_sample(i), 0);
    s->TireSoundBlowOut = in_game_sample("TirePop1");
    bsample_set_category(s->TireSoundBlowOut, 0);
    s->EngineSound = NULL;
    s->TireSound[1] = NULL;
    s->TireSound[0] = NULL;
    if (c->pCarTypeInfo->UsageType == CAR_USAGE_TYPE_COP) {
        SirenSound3d *siren = bMalloc(sizeof(SirenSound3d), "SirenSound",
                                      0, 16);

        sirensound3d_construct(siren);
        s->SirenSound = siren;
    } else {
        s->SirenSound = NULL;
    }
}

void basecarsound_destroy(BaseCarSound *s, int32_t flags)
{
    s->Sound._vtable = BASECARSOUND_VTABLE;
    if (s->HornSound != NULL)
        s3d_destroy(s->HornSound, 3);
    if (s->EngineSound != NULL)
        s3d_destroy(s->EngineSound, 3);
    if (s->SirenSound != NULL)
        s3d_destroy(s->SirenSound, 3);
    if (s->TireSound[0] != NULL)
        s3d_destroy(s->TireSound[0], 3);
    if (s->TireSound[1] != NULL)
        s3d_destroy(s->TireSound[1], 3);
    sound3d_destroy(&s->Sound, flags);
}

void basecarsound_update(BaseCarSound *s, float volume, uint16_t azimuth,
                         float pitch)
{
    (void)azimuth;
    sound3d_update(&s->Sound, &s->pCar->State.Position, s->pSoundEnvelope);
    s->Sound.Volume *= volume;
    s->Sound.Pitch *= pitch;
    s3d_update(s->HornSound, s->Sound.Volume, s->Sound.Azimuth,
               s->Sound.Pitch);
    if (s->SirenSound != NULL)
        basecarsound_update_siren_sound(s);
    basecarsound_update_splash(s, s->Sound.Volume, &s->SplashLeft,
                               &s->SplashLeftTimer);
    basecarsound_update_splash(s, s->Sound.Volume, &s->SplashRight,
                               &s->SplashRightTimer);
}

void basecarsound_update_siren_sound(BaseCarSound *s)
{
    SirenSound3d *siren = s->SirenSound;

    if (s->Sound.Activated)
        sirensound3d_update_mode(siren, s->pCar->TheSirenMode);
    else if (siren->Sound.Activated)
        s3d_activate(siren, 0);
    s3d_update(siren, s->Sound.Volume, s->Sound.Azimuth, s->Sound.Pitch);
}

BSample *basecarsound_get_horn_sample(BaseCarSound *s)
{
    (void)s;
    return NULL;
}

void basecarsound_trigger_splash(BaseCarSound *s, int32_t right,
                                 int32_t level)
{
    if (right)
        s->SplashRight = level;
    else
        s->SplashLeft = level;
}

// 0x0018d4a0. A splash plays at most once in ten sound frames a side; one
// asked for sooner is dropped.
void basecarsound_update_splash(BaseCarSound *s, float volume,
                                int32_t *splash, int32_t *timer)
{
    (void)s;
    if (*timer != 0)
        (*timer)--;
    if (*splash == 0)
        return;
    if (*timer != 0) {
        *splash = 0;
        return;
    }
    if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled)
        bsample_play(basecarsound_get_splash_sample(-1),
                     volume * (float)*splash, -1.0f, 0.0f);
    *timer = 10;
    *splash = 0;
}

void basecarsound_mute(BaseCarSound *s, int32_t on)
{
    int32_t i;

    s3d_mute(s->HornSound, on);
    if (s->EngineSound != NULL)         // the port's: none before 14-4
        s3d_mute(s->EngineSound, on);
    if (s->SirenSound != NULL)
        s3d_mute(s->SirenSound, on);
    for (i = 0; i < 2; i++)
        if (s->TireSound[i] != NULL)
            s3d_mute(s->TireSound[i], on);
    for (i = 0; i < 3; i++)
        bsample_pause(basecarsound_get_splash_sample(i), on != 0);
}

void basecarsound_trigger_tire_blow_out(BaseCarSound *s)
{
    int32_t i;

    if (SoundEnabled && CarSoundEnabled && CarDamageSoundEnabled)
        bsample_play(s->TireSoundBlowOut, s->Sound.Volume,
                     (float)s->Sound.Azimuth, s->Sound.Pitch);
    for (i = 0; i < 2; i++)
        if (s->TireSound[i] != NULL && gTireSoundTriggerBlowOutFn != NULL)
            gTireSoundTriggerBlowOutFn(s->TireSound[i]);
}

void basecarsound_scale_road_noise(BaseCarSound *s, float f)
{
    int32_t i;

    for (i = 0; i < 2; i++)
        if (s->TireSound[i] != NULL && gTireSoundScaleRoadNoiseFn != NULL)
            gTireSoundScaleRoadNoiseFn(s->TireSound[i], f);
}

int32_t basecarsound_in_sound_sphere(BaseCarSound *s)
{
    return s->Sound.SndToCameraDistance < 130.0f;
}

void basecarsound_start_honk_horn(BaseCarSound *s)
{
    if (SoundEnabled && CarSoundEnabled)
        s3d_activate(s->HornSound, 1);
}

void basecarsound_stop_honk_horn(BaseCarSound *s)
{
    if (SoundEnabled && CarSoundEnabled)
        s3d_activate(s->HornSound, 0);
}

int32_t basecarsound_is_honking(BaseCarSound *s)
{
    if (SoundEnabled && CarSoundEnabled)
        return s->HornSound->Sound.Activated != 0;
    return 0;
}

// The siren is left alone: UpdateSirenSound turns it off.
void basecarsound_deactivate_sound(BaseCarSound *s)
{
    int32_t i;

    s3d_activate(s->HornSound, 0);
    if (s->EngineSound != NULL)
        s3d_activate(s->EngineSound, 0);
    for (i = 0; i < 2; i++)
        if (s->TireSound[i] != NULL)
            s3d_activate(s->TireSound[i], 0);
}

void basecarsound_activate_sound(BaseCarSound *s)
{
    int32_t i;

    if (s->EngineSound != NULL)
        s3d_activate(s->EngineSound, 1);
    for (i = 0; i < 2; i++)
        if (s->TireSound[i] != NULL)
            s3d_activate(s->TireSound[i], 1);
}

BSample *basecarsound_get_splash_sample(int32_t i)
{
    char name[8];

    if (i == -1)
        i = sound_random_int(sound_get(), 3);
    memcpy(name, "Splash1", 8);         // 0x00330928
    name[6] = (char)('1' + i);
    return in_game_sample(name);
}

// ----------------------------------------------------- BasePlayerCarSound

// 0x0018d9a0.
void baseplayercarsound_construct(BasePlayerCarSound *s, Car *c)
{
    TopologyCoordinate *tc;
    HornSound3d *h;
    BSample *hs;

    basecarsound_construct(&s->Base, c);
    s->Base.Sound._vtable = BASEPLAYERCARSOUND_VTABLE;
    bsample_construct(&s->WindSample, 0);
    tc = bMalloc(sizeof(TopologyCoordinate), "..\\indep\\src\\carsounds.cpp",
                 773, 16);
    topology_init(tc);
    s->EngineReflectionLeft = 0;
    s->EngineReflectionRight = 0;
    s->ReverbTopologyCoordinate = tc;
    s->CheckForReflected = 1;
    s->Base.pSoundEnvelope = &BasePlayerCarSoundEnvelope;
    bsample_initialize_copy(&s->WindSample, in_game_sample("Wind"));
    bsample_set_category(&s->WindSample, 0);

    // new HornSound3d(GetHornSample()), the call not through the table.
    h = bMalloc(sizeof(HornSound3d), "HornSound3d", 0, 16);
    hs = baseplayercarsound_get_horn_sample(s);
    hornsound3d_construct(h, hs);
    s->Base.HornSound = h;

    s->Base.EngineSound = gCreatePlayerEngineFn != NULL
                          ? gCreatePlayerEngineFn(c) : NULL;
    s->Base.TireSound[0] = gCreatePlayerTireFn != NULL
                           ? gCreatePlayerTireFn(c, 0) : NULL;
    if (TheRaceParameters.NumPlayerCars == 1)
        s->Base.TireSound[1] = gCreatePlayerTireFn != NULL
                               ? gCreatePlayerTireFn(c, 1) : NULL;

    // Split screen: the first player's car to the left, the second's right.
    s->PlayerAzimuth = 0;
    if (TheRaceParameters.NumPlayerCars >= 2) {
        if (c->DriverNumber == 0)
            s->PlayerAzimuth = (uint16_t)-CarSoundMultiPlayerAzimuth;
        else if (c->DriverNumber == 1)
            s->PlayerAzimuth = CarSoundMultiPlayerAzimuth;
    }
    sound3d_activate(&s->Base.Sound, 1);
}

// 0x0018db78.
void baseplayercarsound_destroy(BasePlayerCarSound *s, int32_t flags)
{
    s->Base.Sound._vtable = BASEPLAYERCARSOUND_VTABLE;
    bsample_stop(&s->WindSample);
    if (s->ReverbTopologyCoordinate != NULL) {
        topology_destroy(s->ReverbTopologyCoordinate);
        bFree(s->ReverbTopologyCoordinate);
    }
    bsample_destruct(&s->WindSample);
    basecarsound_destroy(&s->Base, flags);
}

// 0x0018dbf0.
void baseplayercarsound_update(BasePlayerCarSound *s, float volume,
                               uint16_t azimuth, float pitch)
{
    BaseCarSound *b = &s->Base;
    Player *p;
    float engine, tires;
    int32_t i;

    basecarsound_update(b, volume, azimuth, pitch);
    b->Sound.Azimuth = s->PlayerAzimuth;
    engine = b->Sound.Volume * carsound_get_pov_volume(b->pCar, 0);
    tires = b->Sound.Volume * carsound_get_pov_volume(b->pCar, 1);
    if (b->EngineSound != NULL)         // the port's: none before 14-4
        s3d_update(b->EngineSound, engine, b->Sound.Azimuth, b->Sound.Pitch);
    for (i = 0; i < 2; i++)
        if (b->TireSound[i] != NULL)
            s3d_update(b->TireSound[i], tires, b->Sound.Azimuth,
                       b->Sound.Pitch);
    baseplayercarsound_update_engine_reflection(s, b->Sound.Volume,
                                                b->Sound.Azimuth,
                                                b->Sound.Pitch);

    // The zone's sound (a tunnel's, say) goes once the car has left it.
    p = b->pCar->pPlayer;
    if (p->pZoneSample != NULL && p->nZoneCurrent == 0)
        player_clear_zone_sound(p);
}

// 0x0018dd10.
void baseplayercarsound_mute(BasePlayerCarSound *s, int32_t on)
{
    Player *p;

    basecarsound_mute(&s->Base, on);
    bsample_pause(&s->WindSample, on != 0);
    bsample_pause(baseplayercarsound_get_engine_reflection_sample(s, 0),
                  on != 0);
    bsample_pause(baseplayercarsound_get_engine_reflection_sample(s, 1),
                  on != 0);
    p = s->Base.pCar->pPlayer;
    if (p->pZoneSample != NULL)
        bsample_pause((BSample *)p->pZoneSample, on != 0);
}

BSample *baseplayercarsound_get_horn_sample(BasePlayerCarSound *s)
{
    const SoundInfo *info = &s->Base.pCar->pCarTypeInfo->Sound;
    char name[16];

    // bStrCat(name, Prefix, "Horn"): the car's own horn, in its region.
    strcpy(name, info->Prefix);
    strcat(name, "Horn");               // 0x00330938
    return bregion_sample(bsound_region(bsound_get(), info->BaseName), name);
}

BSample *baseplayercarsound_get_engine_reflection_sample(
    BasePlayerCarSound *s, int32_t i)
{
    char name[13];

    (void)s;
    if (i == -1)
        i = sound_random_int(sound_get(), 2);
    memcpy(name, "Reflection01", 13);   // 0x002b4840
    name[11] = (char)('1' + i);
    return in_game_sample(name);
}

// 0x0018de68 and 0x0018dea0. Nothing calls either.
float baseplayercarsound_calc_wind_volume(BasePlayerCarSound *s, float f)
{
    return (carsound_get_pov_volume(s->Base.pCar, 2) * f) * 0.012f;
}

float baseplayercarsound_calc_wind_pitch(BasePlayerCarSound *s, float f)
{
    (void)s;
    return f * 0.008f;
}

// 0x0018deb0. An echo for each side a car flew past on since the last
// frame, louder and higher the faster this one goes; then, above 50 km/h,
// the cars near enough are looked at for the next.
void baseplayercarsound_update_engine_reflection(BasePlayerCarSound *s,
                                                 float volume,
                                                 uint16_t azimuth,
                                                 float pitch)
{
    (void)azimuth;
    (void)pitch;
    if (s->EngineReflectionLeft || s->EngineReflectionRight) {
        float speed = s->Base.pCar->State.VelocityMagnitude;
        float vol = speed * 0.03f;
        float pit = speed * 0.015f;
        BSample *smp;

        if (s->EngineReflectionLeft) {
            if (SoundEnabled && CarSoundEnabled) {
                smp = baseplayercarsound_get_engine_reflection_sample(s, -1);
                bsample_play(smp, vol * volume, 0.0f, pit - 1.0f);
                bsample_set_azimuth(smp, (uint16_t)-ReflectionAzimuth);
            }
            s->EngineReflectionLeft = 0;
        }
        if (s->EngineReflectionRight) {
            if (SoundEnabled && CarSoundEnabled) {
                smp = baseplayercarsound_get_engine_reflection_sample(s, -1);
                bsample_play(smp, vol * volume, 0.0f, pit - 1.0f);
                bsample_set_azimuth(smp, ReflectionAzimuth);
            }
            s->EngineReflectionRight = 0;
        }
    }
    if (s->Base.pCar->State.VelocityMagnitude < 13.888889f)
        s->CheckForReflected = 1;
    else
        baseplayercarsound_update_dynamic_body_reflections(s);
}

static bVector3 *body_position(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_POSITION);

    return ((VtVectorFn)e->fn)(vt_this(b, e));
}

static bVector3 *body_velocity(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_VELOCITY);

    return ((VtVectorFn)e->fn)(vt_this(b, e));
}

static int32_t body_terrain(CollisionBody *b)
{
    const VtEntry *e = vt_slot(b->_vtable, COLLISIONBODY_VT_GET_TERRAIN_TYPE);

    return ((VtTerrainFn)e->fn)(vt_this(b, e));
}

// 0x0018e018. Every body within 9 of the car along the collision list --
// not a plant, closing at over 50 km/h -- that this frame's step carries
// past the car's nose: its side of the car gets an echo next frame.
void baseplayercarsound_update_dynamic_body_reflections(
    BasePlayerCarSound *s)
{
    CollisionBody *body =
        &s->Base.pCar->pDynamicCollisionBody->Dynamic.Body;
    CollisionBody *first, *last, *o;

    dynamiccollisionbody_get_local_collision_bodies(
        (DynamicCollisionBody *)body, 9.0f, &first, &last);
    // GetNext on first, the list head's own word when first is the head.
    for (o = first->Link.next; o != last; o = o->Link.next) {
        bVector2 local, a, b, d, nv, e, rel;
        const bVector3 *p, *q, *v, *w;
        float dist, dotE, dotD;

        if (o == body)
            continue;
        if (body_terrain(o) == TERRAIN_TYPE_PLANT)
            continue;
        p = body_position(body);
        q = body_position(o);
        {
            float dx = p->x - q->x, dy = p->y - q->y, dz = p->z - q->z;

            dist = ee_sqrt((dx * dx + dy * dy) + dz * dz);   // VU0's order
        }
        if (9.0f < dist)
            continue;
        car_world_to_car(s->Base.pCar, &local,
                         (const bVector2 *)body_position(o));
        w = body_velocity(o);
        v = body_velocity(body);
        rel.x = w->x - v->x;
        rel.y = w->y - v->y;
        if (!(13.888889f < ee_sqrt(rel.x * rel.x + rel.y * rel.y)))
            continue;

        // Where each is a step on, the line between them then, the car's
        // heading and the line between them now.
        p = body_position(body);
        v = body_velocity(body);
        bScaleAdd2(&a, (const bVector2 *)p, (const bVector2 *)v,
                   WorldTimeElapsed);
        q = body_position(o);
        w = body_velocity(o);
        bScaleAdd2(&b, (const bVector2 *)q, (const bVector2 *)w,
                   WorldTimeElapsed);
        d.x = b.x - a.x;
        d.y = b.y - a.y;
        bNormalize2(&d, &d);
        bNormalize2(&nv, (const bVector2 *)body_velocity(body));
        q = body_position(o);
        p = body_position(body);
        e.x = q->x - p->x;
        e.y = q->y - p->y;
        bNormalize2(&e, &e);

        dotE = e.x * nv.x + e.y * nv.y;
        dotD = d.x * nv.x + d.y * nv.y;
        if ((dotE < 0.0f && 0.0f < dotD) || (0.0f < dotE && dotD < 0.0f)) {
            if (local.x < 0.0f)
                s->EngineReflectionLeft = 1;
            else
                s->EngineReflectionRight = 1;
        }
    }
}

// --------------------------------------------------------- BaseAICarSound

// 0x0018e6e8.
void baseaicarsound_construct(BaseAICarSound *s, Car *c)
{
    HornSound3d *h;
    BSample *hs;

    basecarsound_construct(&s->Base, c);
    s->Base.Sound._vtable = BASEAICARSOUND_VTABLE;
    s->Base.pSoundEnvelope = &BaseAICarSoundEnvelope;
    s->Base.EngineSound = gCreateAIEngineFn != NULL
                          ? gCreateAIEngineFn(c) : NULL;

    // new HornSound3d(GetHornSample()): BaseCarSound's, so NULL, and the
    // horn one of the three in turn.
    h = bMalloc(sizeof(HornSound3d), "HornSound3d", 0, 16);
    hs = basecarsound_get_horn_sample(&s->Base);
    hornsound3d_construct(h, hs);
    s->Base.HornSound = h;

    s->Base.TireSound[0] = gCreateAITireFn != NULL ? gCreateAITireFn(c)
                                                   : NULL;
}

void baseaicarsound_destroy(BaseAICarSound *s, int32_t flags)
{
    s->Base.Sound._vtable = BASEAICARSOUND_VTABLE;
    basecarsound_destroy(&s->Base, flags);
}

// 0x0018e800. An AI car not among the closest only keeps its distance.
void baseaicarsound_update(BaseAICarSound *s, float volume,
                           uint16_t azimuth, float pitch)
{
    BaseCarSound *b = &s->Base;

    if (!b->Sound.Activated) {
        const VtEntry *e = vt_slot(b->Sound._vtable, SOUND3D_VT_CAMRELATIVE);

        ((VtCamRelativeFn)e->fn)(vt_this(b, e), &b->pCar->State.Position);
        return;
    }
    basecarsound_update(b, volume * 1.5f, azimuth, pitch);
    if (b->EngineSound != NULL)         // the port's: none before 14-4
        s3d_update(b->EngineSound, b->Sound.Volume, b->Sound.Azimuth,
                   b->Sound.Pitch);
    if (b->TireSound[0] != NULL)
        s3d_update(b->TireSound[0], b->Sound.Volume, b->Sound.Azimuth,
                   b->Sound.Pitch);
}

// ------------------------------------------------------------ HornSound3d

void hornsound3d_construct(HornSound3d *h, BSample *sample)
{
    sound3d_construct(&h->Sound);
    h->Sound._vtable = HORNSOUND3D_VTABLE;
    bsample_construct(&h->HornSample, 0);
    if (sample != NULL)
        bsample_initialize_copy(&h->HornSample, sample);
    else
        bsample_initialize_copy(&h->HornSample,
                                hornsound3d_choose_horn_sample(h));
    bsample_set_category(&h->HornSample, 0);
    h->DetunePitch = 1.0f;
}

void hornsound3d_destroy(HornSound3d *h, int32_t flags)
{
    h->Sound._vtable = HORNSOUND3D_VTABLE;
    bsample_destruct(&h->HornSample);
    sound3d_destroy(&h->Sound, flags);
}

void hornsound3d_activate_sound(HornSound3d *h)
{
    if (SoundEnabled)
        bsample_play(&h->HornSample, 0.0f, 0.0f, 0.0f);
}

void hornsound3d_deactivate_sound(HornSound3d *h)
{
    bsample_stop(&h->HornSample);
}

BSample *hornsound3d_choose_horn_sample(HornSound3d *h)
{
    char name[7];

    (void)h;
    memcpy(name, "Horn01", 7);          // 0x00330920
    name[5] = (char)('1' + (uint8_t)HornCounter);
    HornCounter = (HornCounter + 1) % 3;
    return in_game_sample(name);
}

void hornsound3d_mute(HornSound3d *h, int32_t on)
{
    bsample_pause(&h->HornSample, on != 0);
}

// 0x0018f218. bSample's pitch is an offset from 1.
void hornsound3d_update(HornSound3d *h, float volume, uint16_t azimuth,
                        float pitch)
{
    if (!h->Sound.Activated)
        return;
    bsample_set_volume(&h->HornSample, volume);
    bsample_set_azimuth(&h->HornSample, azimuth);
    bsample_set_pitch(&h->HornSample, h->DetunePitch * pitch - 1.0f);
}

// ----------------------------------------------------------- SirenSound3d

void sirensound3d_construct(SirenSound3d *s)
{
    BRegion *r;
    char name[11];
    int32_t i;

    sound3d_construct(&s->Sound);
    s->Sound._vtable = SIRENSOUND3D_VTABLE;
    for (i = 0; i < 3; i++)
        bsample_construct(&s->SirenSampleTable[i], 0);
    s->SwitchSirenTime = 17.0f;
    for (i = 0; i < 3; i++) {
        memcpy(name, "CopSiren01", 11);
        name[9] = (char)('1' + i);
        r = bsound_region(bsound_get(), "InGame");
        bsample_initialize_copy(&s->SirenSampleTable[i],
                                bregion_sample(r, name));
        bsample_set_category(&s->SirenSampleTable[i], 0);
    }
    // Each cop starts on the siren after the last one's.
    SirenCounter = (SirenCounter + 1) % 3;
    s->CurrentSiren = SirenCounter;
    s->CurrBrokenSirenPitch = 1.0f;
    s->IsSirenBroken = 0;
    s->BrokenSirenPitchTarget = 1.0f;
}

void sirensound3d_destroy(SirenSound3d *s, int32_t flags)
{
    int32_t i;

    s->Sound._vtable = SIRENSOUND3D_VTABLE;
    for (i = 2; i >= 0; i--)
        bsample_destruct(&s->SirenSampleTable[i]);
    sound3d_destroy(&s->Sound, flags);
}

void sirensound3d_update_mode(SirenSound3d *s, int32_t mode)
{
    if (mode == SIREN_MODE_NONE && s->Sound.Activated)
        s3d_activate(s, 0);
    if (mode != SIREN_MODE_NONE && !s->Sound.Activated)
        s3d_activate(s, 1);
    if (s->Sound.Activated)
        s->IsSirenBroken = mode == SIREN_MODE_BROKEN;
}

void sirensound3d_activate_sound(SirenSound3d *s)
{
    if (SoundEnabled)
        bsample_play(&s->SirenSampleTable[s->CurrentSiren], 0.0f, 0.0f,
                     0.0f);
}

void sirensound3d_deactivate_sound(SirenSound3d *s)
{
    bsample_stop(&s->SirenSampleTable[s->CurrentSiren]);
}

void sirensound3d_set_siren_broken(SirenSound3d *s, int32_t on)
{
    s->IsSirenBroken = on;
}

void sirensound3d_mute(SirenSound3d *s, int32_t on)
{
    bsample_pause(&s->SirenSampleTable[s->CurrentSiren], on != 0);
}

// 0x0018f548. Every 17 seconds the next of the three; a silent siren goes
// off, and a broken one wobbles.
void sirensound3d_update(SirenSound3d *s, float volume, uint16_t azimuth,
                         float pitch)
{
    BSample *smp;

    if (volume == 0.0f)
        s3d_activate(s, 0);
    if (!s->Sound.Activated)
        return;
    s->SwitchSirenTime -= WorldTimeElapsed;
    if (s->SwitchSirenTime < 0.0f) {
        bsample_stop(&s->SirenSampleTable[s->CurrentSiren]);
        s->SwitchSirenTime = 17.0f;
        s->CurrentSiren = (s->CurrentSiren + 1) % 3;
    }
    smp = &s->SirenSampleTable[s->CurrentSiren];
    if (bsample_is_playing(smp)) {
        bsample_set_volume(smp, volume);
    } else {
        s->SwitchSirenTime = 17.0f;
        if (SoundEnabled)
            bsample_play(smp, volume, 0.0f, 0.0f);
    }
    if (s->IsSirenBroken)
        pitch *= sirensound3d_get_broken_siren_pitch(s);
    bsample_set_pitch(&s->SirenSampleTable[s->CurrentSiren], pitch - 1.0f);
    bsample_set_azimuth(&s->SirenSampleTable[s->CurrentSiren], azimuth);
}

float sirensound3d_get_broken_siren_pitch(SirenSound3d *s)
{
    if (s->BrokenSirenPitchTarget == s->CurrBrokenSirenPitch)
        s->BrokenSirenPitchTarget =
            sound_random_float(sound_get(), 0.9f) + 0.1f;
    s->CurrBrokenSirenPitch = smooth(s->CurrBrokenSirenPitch,
                                     s->BrokenSirenPitchTarget, 0.03f);
    return s->CurrBrokenSirenPitch;
}

// ------------------------------------------------------------- the tables

#define E(f) { 0, 0, (VtFn)(f) }

static const VtEntry basecarsound_vt[CARSOUND_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(basecarsound_destroy),                            //  8  0x0018d258
    E(sound3d_activate),                                // 16  0x00208b28
    E(basecarsound_update),                             // 24  0x0018d340
    E(basecarsound_mute),                               // 32  0x0018d550
    E(basecarsound_deactivate_sound),                   // 40  0x0018d830
    E(basecarsound_activate_sound),                     // 48  0x0018d8d8
    E(sound3d_update_cam_relative_dist_and_velocity),   // 56  0x00208c78
    E(basecarsound_get_horn_sample),                    // 64  0x0018d480
};

static const VtEntry baseplayercarsound_vt[CARSOUND_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(baseplayercarsound_destroy),                      //  8  0x0018db78
    E(sound3d_activate),                                // 16
    E(baseplayercarsound_update),                       // 24  0x0018dbf0
    E(baseplayercarsound_mute),                         // 32  0x0018dd10
    E(basecarsound_deactivate_sound),                   // 40
    E(basecarsound_activate_sound),                     // 48
    E(sound3d_update_cam_relative_dist_and_velocity),   // 56
    E(baseplayercarsound_get_horn_sample),              // 64  0x0018dda0
};

static const VtEntry baseaicarsound_vt[CARSOUND_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(baseaicarsound_destroy),                          //  8  0x0018e7e8
    E(sound3d_activate),                                // 16
    E(baseaicarsound_update),                           // 24  0x0018e800
    E(basecarsound_mute),                               // 32
    E(basecarsound_deactivate_sound),                   // 40
    E(basecarsound_activate_sound),                     // 48
    E(sound3d_update_cam_relative_dist_and_velocity),   // 56
    E(basecarsound_get_horn_sample),                    // 64
};

static const VtEntry hornsound3d_vt[HORNSOUND3D_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(hornsound3d_destroy),                             //  8  0x0018f2b0
    E(sound3d_activate),                                // 16
    E(hornsound3d_update),                              // 24  0x0018f218
    E(hornsound3d_mute),                                // 32  0x0018f208
    E(hornsound3d_deactivate_sound),                    // 40  0x0018f188
    E(hornsound3d_activate_sound),                      // 48  0x0018f160
    E(sound3d_update_cam_relative_dist_and_velocity),   // 56
};

static const VtEntry sirensound3d_vt[SIRENSOUND3D_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(sirensound3d_destroy),                            //  8  0x0018f710
    E(sound3d_activate),                                // 16
    E(sirensound3d_update),                             // 24  0x0018f548
    E(sirensound3d_mute),                               // 32  0x0018f528
    E(sirensound3d_deactivate_sound),                   // 40  0x0018f508
    E(sirensound3d_activate_sound),                     // 48  0x0018f4d0
    E(sound3d_update_cam_relative_dist_and_velocity),   // 56
};

#undef E

void carsound_install_vtables(void)
{
    vt_install(BASECARSOUND_VTABLE, basecarsound_vt, CARSOUND_VT_ENTRIES);
    vt_install(BASEPLAYERCARSOUND_VTABLE, baseplayercarsound_vt,
               CARSOUND_VT_ENTRIES);
    vt_install(BASEAICARSOUND_VTABLE, baseaicarsound_vt, CARSOUND_VT_ENTRIES);
    vt_install(HORNSOUND3D_VTABLE, hornsound3d_vt, HORNSOUND3D_VT_ENTRIES);
    vt_install(SIRENSOUND3D_VTABLE, sirensound3d_vt, SIRENSOUND3D_VT_ENTRIES);
}
