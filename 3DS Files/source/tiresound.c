#include "tiresound.h"

#include <math.h>
#include <stddef.h>

#include "bmem.h"
#include "car.h"
#include "carinit.h"
#include "carsound.h"
#include "eefpu.h"
#include "jukebox.h"
#include "realtime.h"
#include "sound.h"
#include "terraintype.h"
#include "track.h"
#include "vtable.h"

float    PlayerTireSoundOneShotTimeDelay;       // gp-16244
float    TireNoisePitchScale = 0.0065f;         // gp-16232
uint16_t ThumperAzimuthOffset = 8192;           // gp-13344

// --------------------------------------------------------------- helpers

// max<float> (0x001365e0) and min<float> (0x001365f0): max.s and min.s
// with the arguments the other way round.
static float max_f(float a, float b)
{
    return b < a ? a : b;
}

static float min_f(float a, float b)
{
    return a < b ? a : b;
}

// clamp<float> (0x00136600).
static float clamp_f(float x, float lo, float hi)
{
    return min_f(max_f(x, lo), hi);
}

// smooth<float> (0x00136630): `a` a step of at most `step` towards `b`.
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

// How far a wheel slips, its WheelSlip's length.
static float slip_length(const Car *c, int32_t i)
{
    const bVector2 *v = &c->State.WheelSlip[i];

    return ee_sqrt(v->x * v->x + v->y * v->y);
}

static const TerrainTypeInfo *terrain_info(const Car *c, int32_t i)
{
    return &TerrainTypeInfoTable[c->State.WheelTerrain[i]];
}

// The car's blown tyres; retail reads the byte signed.
static int32_t blown_tires(const Car *c)
{
    return (int8_t)c->NumBlownTires;
}

// -------------------------------------------------------- BaseTireSound

void basetiresound_construct(BaseTireSound *s)
{
    sound3d_construct(&s->Sound);
    s->Sound._vtable = BASETIRESOUND_VTABLE;
    bsample_construct(&s->TireFlop, 0);
    bsample_construct(&s->BottomOut, 0);
    s->RearTireTouching = 1;
    s->FrontTireTouching = 1;
    bsample_initialize_copy(&s->TireFlop,
                            sound_get_in_game_sample(sound_get(), "TireFlop"));
    bsample_set_category(&s->TireFlop, 1);
    bsample_initialize_copy(&s->BottomOut,
                            sound_get_in_game_sample(sound_get(), "BottomOut"));
    bsample_set_category(&s->BottomOut, 1);
}

void basetiresound_destroy(BaseTireSound *s, int32_t flags)
{
    s->Sound._vtable = BASETIRESOUND_VTABLE;
    bsample_destruct(&s->BottomOut);
    bsample_destruct(&s->TireFlop);
    sound3d_destroy(&s->Sound, flags);
}

void basetiresound_mute(BaseTireSound *s, int32_t on)
{
    bsample_pause(&s->TireFlop, on != 0);
    bsample_pause(&s->BottomOut, on != 0);
}

// A wheel that was off the ground and is on it again lands: the flop, as
// loud as the car falls fast and turns, and past 0.9 the bottom-out, at a
// random pitch. Side 0 watches wheels 1 and 3, side 1 wheels 0 and 2, and
// -1 the front pair and the rear pair. The touching flags keep the byte
// as the car has it.
void basetiresound_update_tire_impact(BaseTireSound *s, Car *c, CarSide side)
{
    const int8_t *t = c->State.WheelTouchingGround;
    int32_t front = 0, rear = 0;

    if (side == -1) {
        front = t[0] != 0 || t[1] != 0;
        rear = t[2] != 0 || t[3] != 0;
    } else if (side == 0) {
        front = t[1];
        rear = t[3];
    } else if (side == 1) {
        front = t[0];
        rear = t[2];
    }
    if ((front != 0 && s->FrontTireTouching == 0)
        || (rear != 0 && s->RearTireTouching == 0)) {
        const bVector3 *w = &c->State.AngularVelocity;
        float impact = (fabsf(c->State.Velocity.z) * 0.3f      // gp-27524
                        + ee_sqrt(w->x * w->x + w->y * w->y) * 0.8f)
                       * 0.5f;                                  // gp-27520
        float flop = (1.0f < impact ? 1.0f : impact) * s->Sound.Volume;

        if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled) {
            bsample_play(&s->TireFlop, flop, 0.0f, 0.0f);
            bsample_set_azimuth(&s->TireFlop, s->Sound.Azimuth);
        }
        if (0.9f < impact && SoundEnabled && CarSoundEnabled          // gp-27516
            && RoadNoiseEnabled) {
            float pitch = sound_random_float(sound_get(), 0.7f)       // gp-27512
                          + -0.4f;                                    // gp-27508

            if (s->BottomOut.category == 0xffffffffu)
                impact *= jb_saved_volume(sound_get()->jb, 0);
            bsample_play(&s->BottomOut, impact * s->Sound.Volume * 0.8f,
                         0.0f, pitch);                                // gp-27504
            bsample_set_azimuth(&s->BottomOut, s->Sound.Azimuth);
        }
    }
    s->RearTireTouching = (uint16_t)rear;
    s->FrontTireTouching = (uint16_t)front;
}

void basetiresound_trigger_tire_blow_out(BaseTireSound *s)
{
    (void)s;
}

void basetiresound_scale_road_noise(BaseTireSound *s, float f)
{
    (void)s;
    (void)f;
}

// ------------------------------------------------------- TerrainOneShot

void terrainoneshot_init(TerrainOneShot *t, BSample *sample, float *pTimeDelay,
                         CarSide side)
{
    if (sample == NULL) {
        t->bFoundSample = 0;
        return;
    }
    t->bFoundSample = 1;
    t->pTimeDelay = pTimeDelay;
    t->Side = side;
    t->bOnTerrainType = 0;
    bsample_initialize_copy(&t->TerrainSample, sample);
    bsample_set_category(&t->TerrainSample, 1);
}

void terrainoneshot_destroy(TerrainOneShot *t, int32_t flags)
{
    bsample_destruct(&t->TerrainSample);
    if (flags & 1)
        bFree(t);
}

void terrainoneshot_mute(TerrainOneShot *t, int32_t on)
{
    if (t->bFoundSample)
        bsample_pause(&t->TerrainSample, on != 0);
}

// Side 0 watches wheels 0 and 1, and any other 3 and 2, by the terrain each
// has crossed this step. The azimuth goes in as the pan, as retail has it.
void terrainoneshot_update(TerrainOneShot *t, Car *c, int32_t terrain,
                           float volume, uint16_t azimuth, float pitch)
{
    int32_t delayed;

    if (!t->bFoundSample)
        return;
    if (c->State.CrossedWheelTerrain[t->Side == 0 ? 0 : 3] != terrain
        && c->State.CrossedWheelTerrain[t->Side == 0 ? 1 : 2] != terrain) {
        t->bOnTerrainType = 0;
        return;
    }
    delayed = t->pTimeDelay != NULL && 0.0f < *t->pTimeDelay;
    if (t->bOnTerrainType || delayed)
        return;
    bsample_play(&t->TerrainSample, volume, (float)azimuth, pitch - 1.0f);
    t->bOnTerrainType = 1;
    if (t->pTimeDelay != NULL)
        *t->pTimeDelay = 0.3f;                          // gp-27500
}

// ------------------------------------------------------ PlayerTireSound

void playertiresound_construct(PlayerTireSound *s, Car *c, CarSide side)
{
    SoundModule *m = sound_get();
    BRegion *r;

    basetiresound_construct(&s->Base);
    s->pCar = c;
    s->Side = side;
    s->Mode = 0;
    s->Base.Sound._vtable = PLAYERTIRESOUND_VTABLE;
    bsample_construct(&s->MetalBump.TerrainSample, 0);
    s->MetalBump.bFoundSample = 0;
    s->MetalBump.bOnTerrainType = 0;
    s->MetalBump.pTimeDelay = NULL;
    bsample_construct(&s->PotHole.TerrainSample, 0);
    s->PotHole.bFoundSample = 0;
    s->PotHole.bOnTerrainType = 0;
    s->PotHole.pTimeDelay = NULL;
    bsample_construct(&s->LeavesNoise, 0);
    bsample_construct(&s->RoadNoise, 0);
    bsample_construct(&s->DirtNoise, 0);
    bsample_construct(&s->RoadSkid, 0);
    bsample_construct(&s->DirtSkid, 0);
    bsample_construct(&s->Squall, 0);
    bsample_construct(&s->DirtSquall, 0);
    bsample_construct(&s->BurnOutPeel, 0);
    bsample_construct(&s->Busted, 0);
    bsample_construct(&s->BustedScrape, 0);

    bsample_initialize_copy(&s->RoadNoise,
                            sound_get_in_game_sample(m, "RoadNoise"));
    bsample_set_category(&s->RoadNoise, 1);
    bsample_initialize_copy(&s->DirtNoise,
                            sound_get_in_game_sample(m, "GravelNoise"));
    bsample_set_category(&s->DirtNoise, 1);
    bsample_initialize_copy(&s->RoadSkid,
                            sound_get_in_game_sample(m, "LongitudinalSkid"));
    bsample_set_category(&s->RoadSkid, 1);
    bsample_initialize_copy(&s->DirtSkid,
                            sound_get_in_game_sample(m, "GravelSkid"));
    bsample_set_category(&s->DirtSkid, 1);
    bsample_initialize_copy(&s->Squall,
                            sound_get_in_game_sample(m, "SquallSkid"));
    bsample_set_category(&s->Squall, 1);
    bsample_initialize_copy(&s->Busted,
                            sound_get_in_game_sample(m, "TireFlat"));
    bsample_set_category(&s->Busted, 1);
    bsample_initialize_copy(&s->BustedScrape,
                            sound_get_in_game_sample(m, "CrashMetalScrape"));
    bsample_set_category(&s->BustedScrape, 1);
    bsample_initialize_copy(&s->BurnOutPeel,
                            sound_get_in_game_sample(m, "BurnOutPeel"));
    bsample_set_category(&s->BurnOutPeel, 1);
    bsample_initialize_copy(&s->DirtSquall,
                            sound_get_in_game_sample(m, "GravelSkid"));
    bsample_set_category(&s->DirtSquall, 1);
    // No category: UpdateTireImpact scales the player's bottom-out by the
    // saved effects volume itself.
    bsample_set_category(&s->Base.BottomOut, 0xffffffffu);

    // With no track region the flag is left as bMalloc gave it, which is
    // zero here.
    r = bsound_region(bsound_get(), CurrentTrackInfo->SoundRegion);
    if (r != NULL) {
        BSample *leaves = bregion_sample(r, "Leaves");

        if (leaves != NULL) {
            s->FoundLeavesSample = 1;
            bsample_initialize_copy(&s->LeavesNoise, leaves);
            bsample_set_category(&s->LeavesNoise, 1);
        } else {
            s->FoundLeavesSample = 0;
        }
    }
    terrainoneshot_init(&s->MetalBump,
                        sound_get_in_game_sample(m, "MetalBump"),
                        &PlayerTireSoundOneShotTimeDelay, s->Side);
    terrainoneshot_init(&s->PotHole, sound_get_in_game_sample(m, "TireFlop"),
                        &PlayerTireSoundOneShotTimeDelay, s->Side);
    if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled)
        bsample_play(&s->RoadNoise, 0.0f, 0.0f, 0.0f);
    s->PrevShouldMakeRoadNoise = 1;
    playertiresound_reset_thumper_time(s);
    s->PlayThumperSounds = 0;
    s->CurrSquallVolume = 0.0f;
    s->LockedRearPitch = -1.0f;
    s->RoadNoiseScale = 1.0f;
    s->CurrSquallPitch = 1.0f;
    sound3d_activate(&s->Base.Sound, 1);
}

void playertiresound_destroy(PlayerTireSound *s, int32_t flags)
{
    s->Base.Sound._vtable = PLAYERTIRESOUND_VTABLE;
    bsample_stop(&s->RoadNoise);
    bsample_stop(&s->DirtNoise);
    bsample_stop(&s->RoadSkid);
    bsample_stop(&s->DirtSkid);
    bsample_stop(&s->Squall);
    bsample_stop(&s->DirtSquall);
    bsample_stop(&s->BurnOutPeel);
    bsample_stop(&s->Busted);
    bsample_stop(&s->BustedScrape);
    bsample_stop(&s->LeavesNoise);
    bsound_flush(bsound_get(), 1);
    bsample_destruct(&s->BustedScrape);
    bsample_destruct(&s->Busted);
    bsample_destruct(&s->BurnOutPeel);
    bsample_destruct(&s->DirtSquall);
    bsample_destruct(&s->Squall);
    bsample_destruct(&s->DirtSkid);
    bsample_destruct(&s->RoadSkid);
    bsample_destruct(&s->DirtNoise);
    bsample_destruct(&s->RoadNoise);
    bsample_destruct(&s->LeavesNoise);
    terrainoneshot_destroy(&s->PotHole, 2);
    terrainoneshot_destroy(&s->MetalBump, 2);
    basetiresound_destroy(&s->Base, flags);
}

void playertiresound_deactivate_sound(PlayerTireSound *s)
{
    (void)s;
}

void playertiresound_activate_sound(PlayerTireSound *s)
{
    (void)s;
}

void playertiresound_set_sample_pitch(PlayerTireSound *s, BSample *smp,
                                      float pitch)
{
    (void)s;
    bsample_set_pitch(smp, pitch - 1.0f);
}

// The squall's volume eases, up 0.075 a frame and down 0.15.
void playertiresound_calc_tire_squall_volume_and_pitch(PlayerTireSound *s,
                                                       float *volume,
                                                       float *pitch)
{
    float v = playertiresound_calc_tire_squall_volume(s);
    float cur;

    s->CurrSquallPitch = playertiresound_calc_tire_squall_pitch(s);
    cur = s->CurrSquallVolume;
    if (v < cur) {
        float down = cur - 0.15f;                       // gp-27496

        if (v < down)
            v = down;
        s->CurrSquallVolume = v;
        *volume = v;
    } else if (cur < v) {
        float up = cur + 0.075f;                        // gp-27492

        if (up < v)
            v = up;
        s->CurrSquallVolume = v;
        *volume = v;
    } else {
        *volume = cur;
    }
    *pitch = s->CurrSquallPitch;
}

// The skid from the slip of the side's two wheels, each counted from 0.25.
// Side 1 reads the rear pair and holds its pitch from the skid's first
// frame until it stops; any other side reads the front pair.
void playertiresound_calc_tire_skid_volume_and_pitch(PlayerTireSound *s,
                                                     float *volume,
                                                     float *pitch)
{
    const Car *c = s->pCar;
    float a = 0.0f, b, t;
    int32_t i0 = 0, i1 = 1;

    *pitch = 1.0f;
    *volume = 0.0f;
    if (s->Side == 1) {
        i0 = 2;
        i1 = 3;
    }
    if (c->State.WheelTouchingGround[i0])
        a = slip_length(c, i0);
    if (a < 0.25f)
        a = 0.0f;
    b = 0.0f;
    if (c->State.WheelTouchingGround[i1])
        b = slip_length(c, i1);
    if (b < 0.25f)
        b = 0.0f;
    t = (float)((double)(a + b) * 0.5);
    if (s->Side == 1) {
        if (t < 0.01f) {                                // gp-27488
            s->LockedRearPitch = -1.0f;
            return;
        }
        *volume = t * 0.3f;                             // gp-27484
        if (s->LockedRearPitch == -1.0f) {
            *pitch = *pitch * 0.06f * t;                // gp-27480
            *pitch = clamp_f(*pitch, 1.0f, 1.2f);       // gp-27476
            s->LockedRearPitch = *pitch;
        } else {
            *pitch = s->LockedRearPitch;
        }
    } else {
        *volume = t * 0.4f;                             // gp-27472
        *pitch = *pitch * 0.07f * t;                    // gp-27468
        *pitch = clamp_f(*pitch, 1.0f, 1.25f);
    }
}

// The road noise from how fast the side's two wheels on the ground spin:
// side 0 wheels 1 and 2, side 1 wheels 0 and 3.
float playertiresound_calc_tire_noise_volume(PlayerTireSound *s)
{
    const Car *c = s->pCar;
    float a = 0.0f, b = 0.0f, v;

    if (s->Side == 0 || s->Side == 1) {
        int32_t i0 = s->Side == 0 ? 1 : 0;
        int32_t i1 = s->Side == 0 ? 2 : 3;

        if (c->State.WheelTouchingGround[i0])
            a = fabsf(c->State.WheelAngularVelocity[i0]) * 0.0095f;
        if (c->State.WheelTouchingGround[i1])
            b = fabsf(c->State.WheelAngularVelocity[i1]) * 0.0095f;
    }                                       // gp-27464, gp-27460, gp-27456
    v = (a + b) * 0.5f;
    if (1.0f < v)
        v = 1.0f;
    return v;
}

float playertiresound_calc_tire_noise_pitch(PlayerTireSound *s)
{
    const Car *c = s->pCar;
    float a = 0.0f, b = 0.0f;

    if (s->Side == 0 || s->Side == 1) {
        int32_t i0 = s->Side == 0 ? 1 : 0;
        int32_t i1 = s->Side == 0 ? 2 : 3;

        if (c->State.WheelTouchingGround[i0])
            a = fabsf(c->State.WheelAngularVelocity[i0]);
        if (c->State.WheelTouchingGround[i1])
            b = fabsf(c->State.WheelAngularVelocity[i1]);
    }
    return TireNoisePitchScale * (b < a ? a : b)
           + (s->Side == 0 ? 0.15f : 0.0f);             // gp-27452
}

// Above 11 m/s, the side's two wheels' traction usage: side 0 wheels 0 and
// 3, side 1 wheels 1 and 2, and any other wheel 0 twice. Silent until their
// mean is past 0.7.
float playertiresound_calc_tire_squall_volume(PlayerTireSound *s)
{
    const Car *c = s->pCar;
    int32_t i0 = 0, i1 = 0;
    float a = 0.0f, b = 0.0f, m, v = 0.0f;

    if (fabsf(c->State.VelocityMagnitude) < 11.0f)
        return 0.0f;
    if (s->Side == 0) {
        i1 = 3;
    } else if (s->Side == 1) {
        i0 = 1;
        i1 = 2;
    }
    if (c->State.WheelTouchingGround[i0])
        a = fabsf(c->State.WheelTractionUsage[i0]);
    if (c->State.WheelTouchingGround[i1])
        b = fabsf(c->State.WheelTractionUsage[i1]);
    m = (a + b) * 0.5f;
    if (0.7f < m)                                       // gp-27448
        v = m * 1.975f;                                 // gp-27444
    if (1.0f < v)
        v = 1.0f;
    return v;
}

// Retail reads two wheels' traction usage here as well, and drops them.
float playertiresound_calc_tire_squall_pitch(PlayerTireSound *s)
{
    return s->pCar->State.VelocityMagnitude * 0.01015f  // gp-27440
           + (s->Side == 0 ? 0.15f : 0.0f);             // gp-27436
}

void playertiresound_mute(PlayerTireSound *s, int32_t on)
{
    basetiresound_mute(&s->Base, on);
    bsample_pause(&s->RoadNoise, on != 0);
    bsample_pause(&s->DirtNoise, on != 0);
    bsample_pause(&s->RoadSkid, on != 0);
    bsample_pause(&s->DirtSkid, on != 0);
    bsample_pause(&s->Squall, on != 0);
    bsample_pause(&s->DirtSquall, on != 0);
    bsample_pause(&s->BurnOutPeel, on != 0);
    bsample_pause(&s->Busted, on != 0);
    bsample_pause(&s->BustedScrape, on != 0);
    bsample_pause(&s->LeavesNoise, on != 0);
    terrainoneshot_mute(&s->MetalBump, on);
    terrainoneshot_mute(&s->PotHole, on);
}

// The side's two wheels -- 0 and 3 for side 1, else 1 and 2 -- are on road
// when the terrain under both makes road noise; a puddle under either keeps
// what they were on before it.
void playertiresound_update(PlayerTireSound *s, float volume,
                            uint16_t azimuth, float pitch)
{
    const TerrainTypeInfo *t0, *t1;
    Car *c;
    int32_t onRoad, thump;
    float noise, bias, skid, skidPitch, slip;
    BSample *on, *off;

    if (!s->Base.Sound.Activated)
        return;
    c = s->pCar;
    t0 = terrain_info(c, s->Side != 1);
    t1 = terrain_info(c, s->Side == 1 ? 3 : 2);
    s->Base.Sound.Volume = volume;
    s->Base.Sound.Pitch = pitch;
    s->Base.Sound.Azimuth = azimuth;
    onRoad = t0->ShouldTireMakeRoadSound != 0
             && t1->ShouldTireMakeRoadSound != 0;
    noise = playertiresound_calc_tire_noise_volume(s);
    if (t0->Type == TERRAIN_TYPE_PUDDLE || t1->Type == TERRAIN_TYPE_PUDDLE)
        onRoad = s->PrevShouldMakeRoadNoise;
    else
        s->PrevShouldMakeRoadNoise = onRoad;
    noise *= volume;
    playertiresound_update_leaves(s, noise, azimuth, pitch);
    if (0.0f < PlayerTireSoundOneShotTimeDelay)
        PlayerTireSoundOneShotTimeDelay -= WorldTimeElapsed;
    terrainoneshot_update(&s->MetalBump, s->pCar, TERRAIN_TYPE_METAL_GRATE,
                          volume * 1.3f, azimuth, pitch);       // gp-27432
    terrainoneshot_update(&s->PotHole, s->pCar, TERRAIN_TYPE_POTHOLE,
                          volume * 1.5f, azimuth,
                          pitch * 0.8f);                        // gp-27428

    // The thump of a blown tyre's rim, and on cobbles and boardwalks too.
    thump = t0->Type == TERRAIN_TYPE_COBBLESTONE
            || t1->Type == TERRAIN_TYPE_BOARDWALK;
    if (!(blown_tires(s->pCar) < 1))
        thump |= 1;
    s->PlayThumperSounds = thump;
    if (thump)
        playertiresound_update_thumper_tires(s);
    else
        playertiresound_reset_thumper_time(s);
    basetiresound_update_tire_impact(&s->Base, s->pCar, s->Side);

    // The skid, on road or on dirt, and the other one stopped.
    bias = s->Side == 0 ? 0.15f : 0.0f;                 // gp-27424
    skid = 0.0f;
    skidPitch = 1.0f;
    playertiresound_calc_tire_skid_volume_and_pitch(s, &skid, &skidPitch);
    if (!onRoad)
        skidPitch = bias + 1.0f;
    skid = clamp_f(skid * volume, 0.0f, onRoad ? 3.5f : 2.75f);
    on = onRoad ? &s->RoadSkid : &s->DirtSkid;
    off = onRoad ? &s->DirtSkid : &s->RoadSkid;
    if (SoundEnabled && CarSoundEnabled) {
        if (!bsample_is_playing(on) && 0.0f < skid)
            bsample_play(on, skid, 0.0f, skidPitch - 1.0f);
        if (bsample_is_playing(on) && skid <= 0.0f)
            bsample_stop(on);
    }
    if (bsample_is_playing(off))
        bsample_stop(off);
    if (0.0f < skid) {
        bsample_set_volume(on, skid);
        bsample_set_pitch(on, skidPitch - 1.0f);
        bsample_set_azimuth(on, azimuth);
    } else {
        bsample_stop(on);
    }

    playertiresound_update_squall(s, onRoad, volume, azimuth, pitch);

    // The burn-out: on road, on the throttle, the wheels spinning and the
    // car still slow.
    c = s->pCar;
    slip = (float)((double)(float)((double)(c->State.WheelSlip[2].x
                                            + c->State.WheelSlip[3].x)
                                   * 0.5)
                   + (double)(c->State.WheelSlip[0].x
                              + c->State.WheelSlip[1].x) * 0.5);
    if (onRoad && 0.2f < c->State.Throttle && 3.0f < slip     // gp-27420
        && c->State.VelocityMagnitude < 30.0f) {
        if (SoundEnabled && CarSoundEnabled
            && !bsample_is_playing(&s->BurnOutPeel))
            bsample_play(&s->BurnOutPeel, 0.0f, 0.0f,
                         s->Side == 0 ? 0.15f : 0.0f);         // gp-27416
        {
            float v = slip * 0.0625f;

            bsample_set_volume(&s->BurnOutPeel,
                               (3.0f < v ? 3.0f : v) * volume);
        }
        bsample_set_azimuth(&s->BurnOutPeel, azimuth);
    } else if (bsample_is_playing(&s->BurnOutPeel)) {
        bsample_stop(&s->BurnOutPeel);
    }

    // The road noise, or the gravel. Retail starts the road noise only
    // while the music is silent -- the constructor has started it already
    // -- and passes the azimuth as its pan, and the gravel's pitch as its
    // pan; both as they are.
    if (onRoad) {
        if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled
            && !bsample_is_playing(&s->RoadNoise)
            && bsound_get_category_volume(bsound_get(), 4) == 0.0f)
            bsample_play(&s->RoadNoise, 0.0f, (float)azimuth,
                         playertiresound_calc_tire_noise_pitch(s) - 1.0f);
        bsample_set_volume(&s->RoadNoise, noise * s->RoadNoiseScale);
        bsample_set_azimuth(&s->RoadNoise, azimuth);
        playertiresound_set_sample_pitch(
            s, &s->RoadNoise, playertiresound_calc_tire_noise_pitch(s));
        if (bsample_is_playing(&s->DirtNoise))
            bsample_stop(&s->DirtNoise);
    } else {
        float p = pitch + bias;

        if (SoundEnabled && CarSoundEnabled && RoadNoiseEnabled
            && !bsample_is_playing(&s->DirtNoise))
            bsample_play(&s->DirtNoise, noise, p - 1.0f, 0.0f);
        bsample_set_volume(&s->DirtNoise, noise * s->RoadNoiseScale);
        bsample_set_azimuth(&s->DirtNoise, azimuth);
        playertiresound_set_sample_pitch(s, &s->DirtNoise, p);
        if (bsample_is_playing(&s->RoadNoise))
            bsample_stop(&s->RoadNoise);
    }
}

void playertiresound_update_squall(PlayerTireSound *s, int32_t onRoad,
                                   float volume, uint16_t azimuth,
                                   float pitch)
{
    BSample *on = onRoad ? &s->Squall : &s->DirtSquall;
    BSample *off = onRoad ? &s->DirtSquall : &s->Squall;
    float v = 0.0f, p = 1.0f;

    (void)pitch;
    if (SoundEnabled && bsample_is_playing(off))
        bsample_stop(off);
    playertiresound_calc_tire_squall_volume_and_pitch(s, &v, &p);
    v = v * volume;
    if (on != off && SoundEnabled && CarSoundEnabled) {
        if (!bsample_is_playing(on) && 0.0f < v)
            bsample_play(on, v, 0.0f, p - 1.0f);
        else if (bsample_is_playing(on) && v <= 0.0f)
            bsample_stop(on);
    }
    if (0.0f < v) {
        bsample_set_volume(on, smooth(on->currentVolume, v, 0.05f)); // gp-27412
        bsample_set_pitch(on, p - 1.0f);
        bsample_set_azimuth(on, azimuth);
    } else {
        bsample_stop(on);
    }
}

// The track's leaves under side 0's wheels 0 and 1, or the others' 3 and 2.
// A playing one takes the pitch as given, not as an offset.
void playertiresound_update_leaves(PlayerTireSound *s, float volume,
                                   uint16_t azimuth, float pitch)
{
    int32_t a, b;

    if (!s->FoundLeavesSample)
        return;
    a = s->pCar->State.WheelTerrain[s->Side == 0 ? 0 : 3];
    b = s->pCar->State.WheelTerrain[s->Side == 0 ? 1 : 2];
    if (a == TERRAIN_TYPE_AUTUMN_LEAVES || b == TERRAIN_TYPE_AUTUMN_LEAVES
        || a == TERRAIN_TYPE_AUTUMN_LEAVES_SHOULDER
        || b == TERRAIN_TYPE_AUTUMN_LEAVES_SHOULDER
        || a == TERRAIN_TYPE_ROAD_AUTUMN || b == TERRAIN_TYPE_ROAD_AUTUMN) {
        if (!bsample_is_playing(&s->LeavesNoise)) {
            bsample_play(&s->LeavesNoise, volume, (float)azimuth,
                         pitch - 1.0f);
        } else {
            bsample_set_volume(&s->LeavesNoise, volume);
            bsample_set_azimuth(&s->LeavesNoise, azimuth);
            bsample_set_pitch(&s->LeavesNoise, pitch);
        }
    } else if (bsample_is_playing(&s->LeavesNoise)) {
        bsample_stop(&s->LeavesNoise);
    }
}

void playertiresound_reset_thumper_time(PlayerTireSound *s)
{
    s->UpdateThumperTime = 0.0f;
    if (bsample_is_playing(&s->BustedScrape))
        bsample_stop(&s->BustedScrape);
}

// With a tyre blown (or on cobbles or boardwalk): above 3 m/s a thump each
// 1.9 m travelled, at least 0.035 s apart, an eighth of a turn off the
// car's azimuth towards the side; and with a tyre blown and a wheel down,
// the rim's scrape, louder and higher with speed.
void playertiresound_update_thumper_tires(PlayerTireSound *s)
{
    Car *c = s->pCar;
    int32_t stop = 0;

    s->UpdateThumperTime = s->UpdateThumperTime - WorldTimeElapsed;
    if (s->UpdateThumperTime <= 0.0f) {
        float speed = fabsf(c->State.VelocityMagnitude);

        if (speed < 3.0f) {
            playertiresound_reset_thumper_time(s);
        } else {
            const int8_t *t = c->State.WheelTouchingGround;

            if (t[s->Side != 1] != 0 || t[s->Side == 1 ? 3 : 2] != 0) {
                uint16_t off = s->Side != 0
                               ? (uint16_t)-ThumperAzimuthOffset
                               : ThumperAzimuthOffset;

                if (SoundEnabled && CarSoundEnabled && CarDamageSoundEnabled) {
                    bsample_play(&s->Busted, s->Base.Sound.Volume, 0.0f,
                                 s->Base.Sound.Pitch - 1.0f);
                    bsample_set_azimuth(&s->Busted,
                                        (uint16_t)(off
                                                   + s->Base.Sound.Azimuth));
                }
            }
            if (speed == 0.0f)
                s->UpdateThumperTime = 0.0f;
            else
                s->UpdateThumperTime = ee_div(1.9f, speed); // gp-27408
            if (s->UpdateThumperTime < 0.035f)                // gp-27404
                s->UpdateThumperTime = 0.035f;
        }
    }
    if (blown_tires(c) > 0 && s->PrevShouldMakeRoadNoise != 0
        && (s->Base.FrontTireTouching != 0 || s->Base.RearTireTouching != 0)) {
        float v = s->Base.Sound.Volume
                  * (c->State.VelocityMagnitude * 0.04f);     // gp-27396
        float p = s->Base.Sound.Pitch
                  * (c->State.VelocityMagnitude * 0.004f      // gp-27400
                     + 1.4f);                                 // gp-27392

        if (!bsample_is_playing(&s->BustedScrape)) {
            bsample_play(&s->BustedScrape, v, 0.0f, p - 1.0f);
            bsample_set_azimuth(&s->BustedScrape, s->Base.Sound.Azimuth);
        } else {
            bsample_set_volume(&s->BustedScrape, v);
            bsample_set_azimuth(&s->BustedScrape, s->Base.Sound.Azimuth);
            bsample_set_pitch(&s->BustedScrape, p - 1.0f);
        }
    } else {
        stop = 1;
    }
    if (stop && bsample_is_playing(&s->BustedScrape))
        bsample_stop(&s->BustedScrape);
}

void playertiresound_trigger_tire_blow_out(PlayerTireSound *s)
{
    s->PlayThumperSounds = 1;
}

void playertiresound_scale_road_noise(PlayerTireSound *s, float f)
{
    s->RoadNoiseScale = f;
}

// ---------------------------------------------------- OpponentTireSound

// Inline in CreateAITire.
void opponenttiresound_construct(OpponentTireSound *s, Car *c)
{
    SoundModule *m = sound_get();

    basetiresound_construct(&s->Base);
    s->Base.Sound._vtable = OPPONENTTIRESOUND_VTABLE;
    bsample_construct(&s->RoadSkid, 0);
    bsample_construct(&s->DirtSkid, 0);
    s->pCar = c;
    bsample_initialize_copy(&s->RoadSkid,
                            sound_get_in_game_sample(m, "LongitudinalSkid"));
    bsample_set_category(&s->RoadSkid, 0);
    bsample_initialize_copy(&s->DirtSkid,
                            sound_get_in_game_sample(m, "GravelSkid"));
    bsample_set_category(&s->DirtSkid, 0);
    s->PrevSkid = &s->RoadSkid;
    s->TargetSkidVolume = 0.0f;
    s->CurrSkidVolume = 0.0f;
    sound3d_activate(&s->Base.Sound, 1);
}

void opponenttiresound_destroy(OpponentTireSound *s, int32_t flags)
{
    s->Base.Sound._vtable = OPPONENTTIRESOUND_VTABLE;
    bsample_destruct(&s->DirtSkid);
    bsample_destruct(&s->RoadSkid);
    basetiresound_destroy(&s->Base, flags);
}

// The flop at three quarters the skid's volume, from all four wheels. The
// pitch is not kept.
void opponenttiresound_update(OpponentTireSound *s, float volume,
                              uint16_t azimuth, float pitch)
{
    if (!s->Base.Sound.Activated)
        return;
    s->Base.Sound.Volume = volume;
    s->Base.Sound.Azimuth = azimuth;
    opponenttiresound_update_skids(s, volume, azimuth, pitch);
    s->Base.Sound.Volume = s->Base.Sound.Volume * 0.75f;
    basetiresound_update_tire_impact(&s->Base, s->pCar, -1);
}

void opponenttiresound_mute(OpponentTireSound *s, int32_t on)
{
    basetiresound_mute(&s->Base, on);
    bsample_pause(&s->RoadSkid, on != 0);
    bsample_pause(&s->DirtSkid, on != 0);
}

void opponenttiresound_deactivate_sound(OpponentTireSound *s)
{
    bsample_stop(&s->RoadSkid);
    bsample_stop(&s->DirtSkid);
    if (s->PrevSkid != NULL)
        bsample_stop(s->PrevSkid);
}

void opponenttiresound_activate_sound(OpponentTireSound *s)
{
    (void)s;
}

// Dirt when fewer than two wheels are on terrain that makes road noise.
void opponenttiresound_update_skids(OpponentTireSound *s, float volume,
                                    uint16_t azimuth, float pitch)
{
    const Car *c = s->pCar;
    float worst = 0.0f, p;
    int32_t road = 0, i, dirt;
    BSample *smp;

    (void)pitch;
    for (i = 0; i < 4; i++) {
        float m = 0.0f;

        if (c->State.WheelTouchingGround[i])
            m = slip_length(c, i);
        if (m < 0.25f)
            m = 0.0f;
        worst = max_f(worst, m);
        if (terrain_info(c, i)->ShouldTireMakeRoadSound != 0)
            road++;
    }
    dirt = road < 2;
    p = c->State.VelocityMagnitude * 0.01015f + 0.3f;   // gp-27388, -27384
    s->TargetSkidVolume = (dirt ? 3.5f : 5.0f) * volume;
    if (worst < 10.0f)
        s->TargetSkidVolume = 0.0f;
    s->CurrSkidVolume = smooth(s->CurrSkidVolume, s->TargetSkidVolume,
                               0.35f);                  // gp-27380
    smp = dirt ? &s->DirtSkid : &s->RoadSkid;
    if (s->PrevSkid != smp && bsample_is_playing(s->PrevSkid))
        bsample_stop(s->PrevSkid);
    if (SoundEnabled && CarSoundEnabled) {
        if (!bsample_is_playing(smp) && 0.0f < s->CurrSkidVolume)
            bsample_play(smp, s->CurrSkidVolume, 0.0f, p - 1.0f);
        if (bsample_is_playing(smp) && s->CurrSkidVolume <= 0.0f)
            bsample_stop(smp);
    }
    if (0.0f < s->CurrSkidVolume) {
        bsample_set_volume(smp, s->CurrSkidVolume);
        bsample_set_pitch(smp, p - 1.0f);
        bsample_set_azimuth(smp, azimuth);
    } else {
        bsample_stop(smp);
    }
    s->PrevSkid = smp;
}

// ------------------------------------------------------------ tire_sound

Sound3d *tiresound_create_player(Car *c, int32_t side)
{
    PlayerTireSound *s = bMalloc(sizeof(PlayerTireSound), "PlayerTireSound",
                                 0, 16);

    playertiresound_construct(s, c, side);
    return &s->Base.Sound;
}

Sound3d *tiresound_create_ai(Car *c)
{
    OpponentTireSound *s = bMalloc(sizeof(OpponentTireSound), "kAITireSound",
                                   0, 16);

    opponenttiresound_construct(s, c);
    return &s->Base.Sound;
}

typedef void (*VtVoidFn)(void *self);
typedef void (*VtScaleFn)(void *self, float f);

void tiresound_trigger_blow_out(Sound3d *tire)
{
    const VtEntry *e = vt_slot(tire->_vtable, TIRESOUND_VT_TRIGGER_BLOW_OUT);

    ((VtVoidFn)e->fn)(vt_this(tire, e));
}

void tiresound_scale_road_noise(Sound3d *tire, float f)
{
    const VtEntry *e = vt_slot(tire->_vtable, TIRESOUND_VT_SCALE_ROAD_NOISE);

    ((VtScaleFn)e->fn)(vt_this(tire, e), f);
}

// ------------------------------------------------------------- the tables

#define E(f) { 0, 0, (VtFn)(f) }

// `__pure_virtual` at 24, 40 and 48.
static const VtEntry basetiresound_vt[TIRESOUND_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(basetiresound_destroy),                           //  8  0x00214a78
    E(sound3d_activate),                                // 16  0x00208b28
    { 0, 0, NULL },                                     // 24  Update
    E(basetiresound_mute),                              // 32  0x002125a0
    { 0, 0, NULL },                                     // 40  DeactivateSound
    { 0, 0, NULL },                                     // 48  ActivateSound
    E(sound3d_update_cam_relative_dist_and_velocity),   // 56  0x00208c78
    E(basetiresound_trigger_tire_blow_out),             // 64  0x00214a70
    E(basetiresound_scale_road_noise),                  // 72  0x00214a68
};

static const VtEntry playertiresound_vt[TIRESOUND_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(playertiresound_destroy),                         //  8  0x00212cf0
    E(sound3d_activate),                                // 16
    E(playertiresound_update),                          // 24  0x002135a0
    E(playertiresound_mute),                            // 32  0x002134d8
    E(playertiresound_deactivate_sound),                // 40  0x00212e88
    E(playertiresound_activate_sound),                  // 48  0x00212e90
    E(sound3d_update_cam_relative_dist_and_velocity),   // 56
    E(playertiresound_trigger_tire_blow_out),           // 64  0x00214a00
    E(playertiresound_scale_road_noise),                // 72  0x002149f8
};

static const VtEntry opponenttiresound_vt[TIRESOUND_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(opponenttiresound_destroy),                       //  8  0x002149a0
    E(sound3d_activate),                                // 16
    E(opponenttiresound_update),                        // 24  0x00214928
    E(opponenttiresound_mute),                          // 32  0x002148e0
    E(opponenttiresound_deactivate_sound),              // 40  0x00214898
    E(opponenttiresound_activate_sound),                // 48  0x00214890
    E(sound3d_update_cam_relative_dist_and_velocity),   // 56
    E(basetiresound_trigger_tire_blow_out),             // 64  0x00214a70
    E(basetiresound_scale_road_noise),                  // 72  0x00214a68
};

#undef E

void tiresound_install_vtables(void)
{
    vt_install(BASETIRESOUND_VTABLE, basetiresound_vt, TIRESOUND_VT_ENTRIES);
    vt_install(PLAYERTIRESOUND_VTABLE, playertiresound_vt,
               TIRESOUND_VT_ENTRIES);
    vt_install(OPPONENTTIRESOUND_VTABLE, opponenttiresound_vt,
               TIRESOUND_VT_ENTRIES);
}
