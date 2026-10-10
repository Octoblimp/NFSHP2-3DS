// fillerspeech -- the chase's filler speech. See fillerspeech.h.

#include "fillerspeech.h"

#include <math.h>

#include "bmath.h"
#include "car.h"
#include "pursuit.h"
#include "pursuitchopper.h"
#include "race.h"
#include "speechmgr.h"

// A filler class: retail's vtable's GetBank, IsAppropriate, GetWeight and
// Speak, the first and third constants in every class.
typedef struct FillerClass {
    uint32_t bank;
    uint32_t weight;
    int32_t  (*appropriate)(const tPursuit *p);
    void     (*speak)(tPursuit *p);
} FillerClass;

int32_t tpursuit_is_cop_near_chased_car(const tPursuit *p, float dist)
{
    int32_t i;

    for (i = 0; i < p->nNumCops; i++) {
        const tCop     *c = p->Cops[i];
        const bVector3 *a, *b;
        float           dx, dy, dz;

        if (c == NULL)
            continue;
        a = &c->pMyCar->State.Position;
        b = &p->pChasedCar->State.Position;
        dx = a->x - b->x;
        dy = a->y - b->y;
        dz = a->z - b->z;
        // VU0's `vmul.xyz ; vaddy.x ; vaddz.x`, then the FPU's root.
        if (sqrtf((dx * dx + dy * dy) + dz * dz) < dist)
            return 1;
    }
    return 0;
}

// 0x0022bbb0: the chased car at 80 mph or more (gp-26988, 35.762 m/s).
static int32_t chased_car_reckless(const tPursuit *p)
{
    return 35.76218032836914f <= p->pChasedCar->State.VelocityMagnitude;
}

// The cop classes' test before their own (each its own inline copy): a
// cop on the chase, and one within 65.
static int32_t cop_close(const tPursuit *p)
{
    return p->nNumCops != 0 && tpursuit_is_cop_near_chased_car(p, 65.0f);
}

// ---------------------------------------------------- the helicopter's

// ChopperFillerSpeech::IsAppropriate, 0x00231d50, ChopperMisc's.
static int32_t chopper_misc_ok(const tPursuit *p)
{
    return tpursuit_is_chopper_near_car(p);
}

// ChopperMiscFillerClass::Speak, 0x00231c50: the chatter, with whether
// the chased car is past 30 forward.
static void chopper_misc_speak(tPursuit *p)
{
    speechmgr_raise_rotor_chatter(speechmgr_get_instance(),
                                  30.0f < p->pChasedCar->State.ForwardSpeed);
}

// ChopperTrafficFillerClass, 0x00231c90 and 0x00231c88: traffic over 0.9
// (gp-26840).
static int32_t chopper_traffic_ok(const tPursuit *p)
{
    return tpursuit_is_chopper_near_car(p)
           && 0.9f < TheRaceParameters.TrafficDensity;
}

static void chopper_traffic_speak(tPursuit *p)
{
    (void)p;
    speechmgr_raise_rotor_traffic(speechmgr_get_instance());
}

// ChopperLocationFillerClass, 0x00231cf8 and 0x00231ce8.
static int32_t chopper_location_ok(const tPursuit *p)
{
    return tpursuit_is_chopper_near_car(p) && p->CurrentLandmark != 0;
}

static void chopper_location_speak(tPursuit *p)
{
    speechmgr_raise_rotor_location(speechmgr_get_instance(),
                                   p->CurrentLandmark);
}

// ----------------------------------------------------------- the cops'

// CopLocationFillerClass, 0x00231ba0 and 0x00231b68.
static int32_t cop_location_ok(const tPursuit *p)
{
    return cop_close(p) && p->CurrentLandmark != 0;
}

static void cop_location_speak(tPursuit *p)
{
    uint32_t speaker = tpursuit_get_cop_speaker(p);

    speechmgr_raise_pursuit_update_subject_location(speechmgr_get_instance(),
                                                    speaker,
                                                    p->CurrentLandmark, 0);
}

// CopTacticMiscFillerClass, 0x00231b08 and 0x00231aa8: a divert or a
// cutoff, one time in two each.
static int32_t cop_tactic_misc_ok(const tPursuit *p)
{
    return cop_close(p) && TheRaceParameters.BeACop == 0;
}

static void cop_tactic_misc_speak(tPursuit *p)
{
    if (bRandomI(2, &bDefaultSeed) == 0)
        speechmgr_raise_tactic_divert(speechmgr_get_instance(),
                                      tpursuit_get_cop_speaker(p));
    else
        speechmgr_raise_tactic_cutoff(speechmgr_get_instance(),
                                      tpursuit_get_cop_speaker(p));
}

// CopSpeedFillerClass, 0x00231a20 and 0x002319d8.
static int32_t cop_speed_ok(const tPursuit *p)
{
    return cop_close(p) && 100.0f < tpursuit_get_speed_mph_or_kph(p);
}

static void cop_speed_speak(tPursuit *p)
{
    uint32_t speaker = tpursuit_get_cop_speaker(p);

    speechmgr_raise_current_speed(speechmgr_get_instance(), speaker,
                                  tpursuit_get_speed_mph_or_kph(p));
}

// CopRecklessFillerClass, 0x00231968 and 0x00231940.
static int32_t cop_reckless_ok(const tPursuit *p)
{
    return cop_close(p) && chased_car_reckless(p);
}

// Both the reckless and the direction classes' Speak (0x00231940,
// 0x00231910) raise the reckless update.
static void cop_reckless_speak(tPursuit *p)
{
    speechmgr_raise_update_reckless(speechmgr_get_instance(),
                                    tpursuit_get_cop_speaker(p), 0);
}

// CopDirectionFillerClass's test, 0x00231c10.
static int32_t cop_direction_ok(const tPursuit *p)
{
    return cop_close(p);
}

// TacticHitFillerClass, 0x00231870 and 0x00231820: with the chase's flag
// 4, outside Be A Cop, two different speakers, and a cop within 40.
static int32_t tactic_hit_ok(const tPursuit *p)
{
    uint32_t speaker;

    if ((p->BehaviourFlags & 4u) == 0)
        return 0;
    if (TheRaceParameters.BeACop != 0)
        return 0;
    if (tpursuit_get_secondary_cop_speaker(p) == COP_SPEAKER_NONE)
        return 0;
    speaker = tpursuit_get_cop_speaker(p);
    if (speaker == tpursuit_get_secondary_cop_speaker(p))
        return 0;
    return tpursuit_is_cop_near_chased_car(p, 40.0f);
}

static void tactic_hit_speak(tPursuit *p)
{
    uint32_t speaker = tpursuit_get_cop_speaker(p);

    speechmgr_raise_tactic_hit(speechmgr_get_instance(), speaker,
                               tpursuit_get_secondary_cop_speaker(p));
}

// FillerSpeechBanks, 0x0031c658, as _GLOBAL_$I$FillerSpeechBanks
// (0x002317b0) fills it.
static const FillerClass kFillerBanks[9] = {
    {   1, 4, chopper_location_ok, chopper_location_speak },
    {   2, 4, chopper_traffic_ok,  chopper_traffic_speak  },
    {   4, 4, chopper_misc_ok,     chopper_misc_speak     },
    {   8, 2, cop_location_ok,     cop_location_speak     },
    {  32, 2, cop_tactic_misc_ok,  cop_tactic_misc_speak  },
    {  64, 2, cop_speed_ok,        cop_speed_speak        },
    { 128, 2, cop_reckless_ok,     cop_reckless_speak     },
    { 256, 2, cop_direction_ok,    cop_reckless_speak     },
    {  16, 5, tactic_hit_ok,       tactic_hit_speak       },
};

int32_t try_filler_speech(tPursuit *p, uint32_t *cookie)
{
    const FillerClass *cand[9];
    uint32_t           n = 0, total = 0, r, sum, i;

    for (i = 0; i < 9u; i++) {
        const FillerClass *f = &kFillerBanks[i];

        if ((f->bank & *cookie) != 0)
            continue;
        if (!f->appropriate(p))
            continue;
        cand[n++] = f;
        total += f->weight;
    }
    if (total == 0)
        return 0;
    r = (uint32_t)bRandomI((int32_t)total, &bDefaultSeed);
    sum = 0;
    for (i = 0; i < n; i++) {
        sum += cand[i]->weight;
        if (r < sum) {
            cand[i]->speak(p);
            *cookie |= cand[i]->bank;
            break;
        }
    }
    return 1;
}

void say_filler_speech(tPursuit *p, uint32_t *cookie)
{
    if (try_filler_speech(p, cookie))
        return;
    *cookie = 0;
    try_filler_speech(p, cookie);
}
