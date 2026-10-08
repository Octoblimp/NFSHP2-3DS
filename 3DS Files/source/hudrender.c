// hudrender -- see hudrender.h.

#include "hudrender.h"

#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "bchunk.h"
#include "bprintf.h"
#include "car.h"
#include "cartypeinfo.h"
#include "characterinfo.h"
#include "copmanager.h"
#include "drivetarget.h"
#include "eefpu.h"
#include "flailer.h"
#include "mainloop.h"
#include "player.h"
#include "playerhud.h"
#include "playerinit.h"
#include "race.h"
#include "racecore.h"
#include "raceparams.h"
#include "racesplit.h"
#include "rcstates.h"
#include "realtime.h"
#include "scenery.h"
#include "world.h"

float   SpeedMinFactor          = 0.7f;
int32_t LiveUpdateSplitTimeRate;
float   TachTestRpm             = 100.0f;
int32_t DisplayPlayerDebugInfo;

const char *(*gHudTranslateFn)(int32_t id);
void (*gHudDoAnimationsFn)(struct Player *p);
void (*gUpdateScoringFn)(struct Player *p);
void (*gStartScoreFn)(struct Player *p, int32_t scoring, int32_t value);
void (*gHudStartSpeedAnimationFn)(struct Player *p, struct FlailerTextChunk *a,
                                  struct FlailerTextChunk *b, uint32_t time,
                                  int32_t flag);
void (*gHudStartGrowAnimationFn)(struct Player *p, struct FlailerTextChunk *a,
                                 struct FlailerTextChunk *b, uint32_t time,
                                 int32_t flag);
void (*gUpdatePursuitMeterFn)(struct Player *p, int32_t level);
void (*gUpdateRadarDetectorFn)(struct Player *p);
void (*gDrawTrackerFn)(struct Player *p, struct Car *c, int32_t index);
void (*gNisOverlayUpdateFn)(NISOverlayManager *o, int32_t playing);

const ScoreInfo ScoreInfoTable[NUM_SCORE_INFOS] = {     // 0x002fbbf0
    { 0x495d7, "BEAT THE COPS",    "+2000"  },
    { 0x495d8, "RESET CAR",        "-1000"  },
    { 0x495d9, "HIT COP CAR",      "-1000"  },
    { 0x495da, "CLEAN LAP",        "+2000"  },
    { 0x495db, "LED FIRST LAP",    "+1500"  },
    { 0x495dc, "LED A LAP",        "+1000"  },
    { 0x495dd, "TOP SPEED",        "+1000"  },
    { 0x495de, "CLEAN SEGMENT",    "+500"   },
    { 0x495df, "DODGE ROADBLOCK",  "+500"   },
    { 0x495e0, "SMASH ROADBLOCK",  "+500"   },
    { 0x495e1, "SMACK!",           "+0"     },
    { 0x495e2, "AIR",              "+250"   },
    { 0x495e3, "BIG AIR",          "+250"   },
    { 0x495e4, "HUGE AIR",         "+250"   },
    { 0x495e5, "DRIFT",            "+250"   },
    { 0x495f6, "START BONUS",      "+2000"  },
    { 0x495e6, "TOOK 1ST PLACE",   "+5000"  },
    { 0x495e7, "TOOK 2ND PLACE",   "+2000"  },
    { 0x495e8, "TOOK 3RD PLACE",   "+1000"  },
    { 0x495e9, "TOOK 4TH PLACE",   "+750"   },
    { 0x495ea, "TOOK 5TH PLACE",   "+500"   },
    { 0x495eb, "TOOK 6TH PLACE",   "+250"   },
    { 0x495ec, "TOOK 7TH PLACE",   "+100"   },
    { 0x495ee, "1ST PLACE BONUS",  "+10000" },
    { 0x495ef, "2ND PLACE BONUS",  "+5000"  },
    { 0x495f0, "3RD PLACE BONUS",  "+2500"  },
    { 0x495f1, "SPEEDER BUSTED",   "+2000"  },
    { 0x495f2, "QUOTA FILLED",     "+5000"  },
    { 0x495f3, "BLEW THEIR TIRES", "+500"   },
    { 0x495f4, "BLEW YOUR TIRES",  "-500"   },
};

// GetLetterForGear's pairs, 0x002fbaf8.
static const int8_t kGearLetters[10][2] = {
    { -1, 'A' }, { 0, 'R' }, { 1, 'N' }, { 2, '1' }, { 3, '2' },
    { 4, '3' }, { 5, '4' }, { 6, '5' }, { 7, '6' }, { 8, '7' },
};

// The last whole second TriggerTimerWarningSound played for, gp-13388.
static int32_t sTimerWarningSecond;

#define TXT(o) ((struct FlailerTextChunk *)(void *)(o))
#define BMP(o) ((struct FlailerBitmapChunk *)(void *)(o))

#define HUD_ANY_GAUGE (HUD_GAUGES_IN_CAR | HUD_GAUGES | HUD_GAUGES_OUTSIDE)

// The colours, RGBA with the alpha on top.
#define COLOUR_SHIFT_ON      0x80008000u
#define COLOUR_SHIFT_OFF     0x80002000u
#define COLOUR_GEAR_ENGAGED  0x00808080u
#define COLOUR_GEAR_CLUTCH   0x00404040u
#define COLOUR_LAP_OVER      0x400535beu
#define COLOUR_LAP_WARNING   0x4004d5e2u
#define COLOUR_LAP_COUNTDOWN 0x402aae01u
#define COLOUR_TYRE_GRIP     0x80008000u
#define COLOUR_TYRE_SLIP     0x80000080u
#define COLOUR_BTC_USED      0xff005000u
#define COLOUR_BTC_COMING    0xff500000u
#define COLOUR_BTC_LEFT      0xff000050u
#define COLOUR_DAMAGE_ON     0xff000070u
#define COLOUR_DAMAGE_OFF    0xff000020u
#define COLOUR_TRACK_RACER   0xff0035acu
#define COLOUR_TRACK_COP     0xff800000u

// The string ids.
#define LANG_LEAD_AHEAD    0x18e73
#define LANG_LEAD_BEHIND   0x18e74
#define LANG_PULLED_OVER   0x49446
#define LANG_LAP           0x494aa
#define LANG_LAPS          0x494ae
#define LANG_PLACE_1ST     0xeeac       // plus the place
#define LANG_PLACE_1ST_F   0xeeb5

// The HUD info floats: the gauges' angles and ranges.
#define HUDINFO_TACH_ANGLE0   4
#define HUDINFO_TACH_ANGLE1   8
#define HUDINFO_MPH_ANGLE0   24
#define HUDINFO_MPH_ANGLE1   28
#define HUDINFO_KPH_ANGLE0   32
#define HUDINFO_KPH_ANGLE1   36
#define HUDINFO_MPH_MIN      40
#define HUDINFO_MPH_MAX      44
#define HUDINFO_KPH_MIN      48
#define HUDINFO_KPH_MAX      52

// DisplayDebugInfo's objects on the HUD screen.
#define DEBUG_CFPS_HASH 0xfa10332fu
#define DEBUG_GFPS_HASH 0x2df92633u
#define DEBUG_POS_HASH  0xd8f8bd54u
#define DEBUG_DIST_HASH 0xf8c20c4au

static float hud_info_f(const CarTypeInfo *ti, int off)
{
    float v;

    memcpy(&v, ti->HudInfo + off, sizeof v);
    return v;
}

static int32_t hud_language(void)
{
    return gCurrLanguageFn != NULL ? gCurrLanguageFn() : 0;
}

static const char *hud_translate(int32_t id)
{
    const char *s = gHudTranslateFn != NULL ? gHudTranslateFn(id) : NULL;

    return s != NULL ? s : "";
}

static int timer_word_valid(uint32_t t)
{
    return t != 0 && t != TIMER_UNSET;
}

static void set_vis(struct FlailerObjectChunk *o, int32_t v)
{
    if (o != NULL)
        flailerobject_set_visibility(o, v);
}

static void set_bitmap_colour(struct FlailerObjectChunk *o, uint32_t c)
{
    if (o != NULL)
        flailerbitmap_set_color(BMP(o), c);
}

static void set_string(struct FlailerObjectChunk *o, const char *s)
{
    if (o != NULL)
        flailertext_set_string(TXT(o), s);
}

// PrintToString in the game's language.
static void print_time(const Timer *t, char *buf, int32_t flags)
{
    timer_print_to_string(t, buf, flags, hud_language());
}

// ------------------------------------------------------------ the helpers

char get_letter_for_gear(int32_t gear)
{
    int i;

    for (i = 0; i < 10; i++)
        if (gear == kGearLetters[i][0])
            return (char)kGearLetters[i][1];
    return 'X';
}

void trigger_timer_warning_sound(const Timer *t)
{
    int32_t s = ee_trunc_w((float)(int32_t)t->PackedTime * 0.00025f);

    if (s != sTimerWarningSecond) {
        struct bSample *smp = gGetInGameSampleFn != NULL
            ? gGetInGameSampleFn("TimerCountdown") : NULL;

        if (smp != NULL && gSamplePlayFn != NULL)
            gSamplePlayFn(smp, 1.0f, 0.0f, 0.0f);
        sTimerWarningSecond = s;
    }
}

uint32_t player_get_current_best_lap_record(struct Player *p,
                                            int32_t previous)
{
    const RaceParameters *rp = &TheRaceParameters;
    uint32_t rec = rp->Point2Point != 0
        ? p->PlayerSettings.BestTotalTimeRecord.PackedTime
        : p->PlayerSettings.BestLapTimeRecord.PackedTime;
    struct RacingCar *rc;
    uint32_t t;

    if (rp->RaceType == RACE_TYPE_TIME_TRIAL || rp->Point2Point != 0)
        return rec;
    if (p->MyCar == NULL || pCurrentRace == NULL)
        return rec;
    rc = race_get_racing_car(pCurrentRace, p->MyCar);
    if (rc == NULL)
        return rec;
    t = previous ? racingcar_get_last_previous_best_lap_time(rc)->PackedTime
                 : racingcar_get_last_best_lap_time(rc)->PackedTime;
    if (!timer_word_valid(t))
        return rec;
    if (!timer_word_valid(rec) || (int32_t)t < (int32_t)rec)
        return t;
    return rec;
}

int32_t player_convert_score_string(struct Player *p, const char *s)
{
    int32_t sign = 1;
    uint32_t v = 0;

    (void)p;
    if (s[0] == '-') {
        sign = -1;
        s++;
    } else if (s[0] == '+') {
        s++;
    }
    while (*s >= '0' && *s <= '9')
        v = v * 10 + (uint32_t)(*s++ - '0');
    return (int32_t)((uint32_t)sign * v);
}

void player_fade_score(struct Player *p)
{
    struct FlailerObjectChunk *title = p->pFlailerScoreTitle;
    struct FlailerObjectChunk *total = p->pFlailerScoreTotal;
    float x;
    int32_t a;

    if (p->tScoreAnimation.PackedTime == TIMER_UNSET)
        return;
    if (title == NULL || total == NULL)
        return;
    x = (float)(int32_t)((uint32_t)WorldTimer - p->tScoreAnimation.PackedTime)
        * 0.00025f;
    if (0.0f < x && x <= 0.5f) {
        flailerobject_set_visibility(title, 1);
        flailerobject_set_visibility(total, 1);
        a = ee_trunc_w((x + x) * 128.0f);
    } else if (0.5f < x && x <= 4.5f) {
        flailerobject_set_visibility(title, 1);
        flailerobject_set_visibility(total, 1);
        flailertext_set_alpha(TXT(title), 128);
        flailertext_set_alpha(TXT(total), 128);
        return;
    } else if (4.5f < x && x <= 5.0f) {
        flailerobject_set_visibility(title, 1);
        flailerobject_set_visibility(total, 1);
        a = ee_trunc_w((1.0f - ((x - 4.5f) + (x - 4.5f))) * 128.0f);
    } else {
        if (5.0f < x) {
            flailerobject_set_visibility(title, 0);
            flailerobject_set_visibility(total, 0);
            p->tScoreAnimation.PackedTime = TIMER_UNSET;
        }
        return;
    }
    flailertext_set_alpha(TXT(title), a);
    flailertext_set_alpha(TXT(total), a);
}

void player_display_debug_info(struct Player *p)
{
    struct FlailerObjectChunk **o[4] = {
        &p->pFlailerCFPSString, &p->pFlailerGFPSString,
        &p->pFlailerPosString, &p->pFlailerDistString,
    };
    static const uint32_t hashes[4] = {
        DEBUG_CFPS_HASH, DEBUG_GFPS_HASH, DEBUG_POS_HASH, DEBUG_DIST_HASH,
    };
    struct Car *car;
    char buf[64];
    int32_t zone;
    float km;
    int i;

    for (i = 0; i < 4; i++)
        if (*o[i] == NULL)
            *o[i] = flailer_find_object(p->HudScreenHash, hashes[i],
                                        FLAILER_TYPE_TEXT);
    // The visibility byte written in place, not through SetVisibility.
    for (i = 0; i < 4; i++)
        if (*o[i] != NULL)
            (*o[i])->Visibility = DisplayPlayerDebugInfo != 0
                ? FLAILER_OBJECT_VISIBLE : FLAILER_OBJECT_INVISIBLE;
    if (DisplayPlayerDebugInfo == 0)
        return;

    zone = scenery_get_current_zone_number();
    car = p->MyCar;
    km = car != NULL ? car->State.Odometer * 0.001f : 0.0f;
    b_snprintf(buf, sizeof buf, "C: %dfps", ee_trunc_w(PreviousCpuFrameRate));
    set_string(p->pFlailerCFPSString, buf);
    b_snprintf(buf, sizeof buf, "G: %dfps", ee_trunc_w(PreviousGpuFrameRate));
    set_string(p->pFlailerGFPSString, buf);
    if (car != NULL) {
        b_snprintf(buf, sizeof buf, "%.0f %.0f %.0f s%d",
                 (double)car->State.Position.x, (double)car->State.Position.y,
                 (double)car->State.Position.z, zone);
        set_string(p->pFlailerPosString, buf);
    }
    b_snprintf(buf, sizeof buf, "%f km", (double)km);
    set_string(p->pFlailerDistString, buf);
}

// ------------------------------------------------------------ RenderHud

// A gauge's needle: `n` of the way from a0 to a1 degrees, going up through
// 360 when a1 is the smaller, and kept to [0, 360].
static float needle_angle(float n, float a0, float a1)
{
    float span = a0 < a1 ? a1 - a0 : (360.0f - a0) + a1;
    float ang = a0 + n * span;

    if (360.0f < ang)
        ang = ang - 360.0f;
    if (ang < 0.0f)
        ang = 360.0f - ang;
    return ang;
}

// The speedo, 0x0017f0d8 to 0x0017f45c.
static void render_speed(struct Player *p, struct Car *car,
                         const CarTypeInfo *ti)
{
    float spd, min, max, a0, a1, ratio;
    int32_t s1, t;

    if (TheRaceParameters.GlobalDisplaySettings.Units == 1) {
        spd = car->State.ForwardSpeed * 3.6f;
        min = hud_info_f(ti, HUDINFO_KPH_MIN);
        max = hud_info_f(ti, HUDINFO_KPH_MAX);
        a0 = hud_info_f(ti, HUDINFO_KPH_ANGLE0);
        a1 = hud_info_f(ti, HUDINFO_KPH_ANGLE1);
    } else {
        spd = car->State.ForwardSpeed * 2.237f;
        min = hud_info_f(ti, HUDINFO_MPH_MIN);
        max = hud_info_f(ti, HUDINFO_MPH_MAX);
        a0 = hud_info_f(ti, HUDINFO_MPH_ANGLE0);
        a1 = hud_info_f(ti, HUDINFO_MPH_ANGLE1);
    }
    if (p->TopSpeed == 0)
        p->TopSpeed = ee_trunc_w(p->SpeedFactor * max);
    ratio = spd / max;
    s1 = ee_trunc_w(spd);
    p->bNewTopSpeed = 0;
    if (ratio < SpeedMinFactor)
        p->bCheckTopSpeed = 1;
    if (p->bCheckTopSpeed != 0 && TheRaceParameters.BeACop == 0
        && s1 < p->LastSpeed && p->TopSpeed < p->LastSpeed
        && p->SpeedFactor < ratio) {
        p->SpeedFactor = p->SpeedFactor + 0.1f;
        if (1.0f < p->SpeedFactor)
            p->SpeedFactor = 1.0f;
        p->bCheckTopSpeed = 0;
        p->bNewTopSpeed = 1;
    }

    if (p->pFlailerSpeedNeedle != NULL) {
        float n = (spd - min) / (max - min);

        if (spd < min)
            n = 0.0f;
        if (max < spd)
            n = 1.0f;
        flailerbitmap_set_rotation(BMP(p->pFlailerSpeedNeedle),
                                   needle_angle(n, a0, a1));
    }

    if (p->pFlailerSpeedString != NULL) {
        // Passing each fifty from 100 to 400 pops the digits, but not in
        // the car.
        if ((p->CurrentHudFeatures & HUD_GAUGES_IN_CAR) == 0) {
            for (t = 100; t <= 400; t += 50) {
                if (p->LastSpeed < t && (float)t <= spd) {
                    if (p->pFlailerSpeedString2 != NULL) {
                        flailer_printf_chunk(TXT(p->pFlailerSpeedString2),
                                             "%3d", ee_trunc_w(fabsf(spd)));
                        if (gHudStartSpeedAnimationFn != NULL)
                            gHudStartSpeedAnimationFn(
                                p, TXT(p->pFlailerSpeedString2),
                                TXT(p->pFlailerSpeedString),
                                (uint32_t)WorldTimer, 1);
                    }
                    break;
                }
            }
        }
        flailer_printf_chunk(TXT(p->pFlailerSpeedString), "%3d",
                             ee_trunc_w(fabsf(spd)));
    }
    p->LastSpeed = s1;
}

// The tach, the shift light and the gear, 0x0017f470 to 0x0017f708.
static void render_tach(struct Player *p, struct Car *car,
                        const CarTypeInfo *ti)
{
    const EngineInfo *e = &p->MyCar->pCarTypeInfo->Engine;
    float rpm = TachTestRpm == 100.0f ? car->State.RPM : TachTestRpm;
    float r = rpm / e->MaxRPM;
    float a0, a1;

    if (r < 0.0f)
        r = 0.0f;
    if (1.0f < r)
        r = 1.0f;
    if (p->CurrentHudFeatures & HUD_GAUGES) {
        a0 = hud_info_f(ti, HUDINFO_TACH_ANGLE0);
        a1 = hud_info_f(ti, HUDINFO_TACH_ANGLE1);
    } else {
        a0 = 45.0f;
        a1 = 215.0f;
    }

    if (p->pFlailerShiftUp != NULL) {
        if (p->PlayerSettings.TransmissionType != 1) {
            flailerobject_set_visibility(p->pFlailerShiftUp, 0);
        } else {
            flailerobject_set_visibility(p->pFlailerShiftUp, 1);
            flailerbitmap_set_color(
                BMP(p->pFlailerShiftUp),
                e->RedLineRPM <= rpm && car->State.CurrentGear > 0
                        && p->PlayerSettings.TransmissionType == 1
                    ? COLOUR_SHIFT_ON : COLOUR_SHIFT_OFF);
        }
    }

    if (p->pFlailerTachNeedle != NULL) {
        flailerbitmap_set_rotation(BMP(p->pFlailerTachNeedle),
                                   needle_angle(r, a0, a1));
        // The red band from the red line, in whole 500s.
        if (p->pFlailerTachGradient != NULL) {
            int32_t v = ee_trunc_w(e->RedLineRPM) / 500;
            float g = (float)v * 500.0f / e->MaxRPM * (a1 - a0);

            flailerbitmap_set_rotation(BMP(p->pFlailerTachGradient), a0 + g);
        }
    }

    if (p->pFlailerGearString != NULL) {
        char buf[2];

        buf[0] = get_letter_for_gear(car->State.CurrentGear);
        buf[1] = '\0';
        flailertext_set_string(TXT(p->pFlailerGearString), buf);
        flailertext_set_color(TXT(p->pFlailerGearString),
                              car->State.ClutchEngaged != 0
                                  ? COLOUR_GEAR_ENGAGED : COLOUR_GEAR_CLUTCH);
    }
}

// A two-player race's lead, 0x0017f710 to 0x0017f7b0.
static void render_lead(struct Player *p, Race *race, struct RacingCar *rc)
{
    struct Player *o = p->pOtherPlayer;
    struct RacingCar *other;
    Timer t;
    char buf[16];

    if (o == NULL || o->MyCar == NULL)
        return;
    other = race_get_racing_car(race, o->MyCar);
    if (other == NULL)
        return;
    t.PackedTime = 0;
    race_calculate_split_time(race, &t, other, rc);
    print_time(&t, buf, TIMER_PRINT_SIGN);
    if (p->pFlailerLeadTime != NULL) {
        flailertext_set_string(TXT(p->pFlailerLeadTime), buf);
        flailertext_set_format_options(TXT(p->pFlailerLeadTime),
                                       BUI_FMT_FIXEDWIDTH);
    }
    flailertext_set_language_id(TXT(p->pFlailerLeadTitle),
                                buf[0] == '+' ? LANG_LEAD_AHEAD
                                              : LANG_LEAD_BEHIND);
}

// The lap time, counting down in a time trial, 0x0017f7b4 to 0x0017f98c.
static void render_lap_time(struct Player *p, struct RacingCar *rc)
{
    struct FlailerObjectChunk *o = p->pFlailerLapTime;
    uint32_t ttt = TheRaceParameters.TimeTrialTime.PackedTime;
    uint32_t start = racingcar_get_last_start_line_crossing_time(rc)
        ->PackedTime;
    Timer t;
    char buf[16];

    t.PackedTime = timer_word_valid(start) ? (uint32_t)WorldTimer - start : 0;
    if (timer_word_valid(t.PackedTime) && timer_word_valid(ttt)) {
        if ((float)(int32_t)t.PackedTime * 0.00025f < 3.0f) {
            uint32_t last = racingcar_get_last_lap_time(rc)->PackedTime;

            t.PackedTime = timer_word_valid(last) ? ttt - last
                                                  : ttt - t.PackedTime;
        } else {
            t.PackedTime = ttt - t.PackedTime;
        }
        if ((int32_t)t.PackedTime < 0) {
            t.PackedTime = 0u - t.PackedTime;
            flailertext_set_color(TXT(o), COLOUR_LAP_OVER);
        } else if ((float)(int32_t)t.PackedTime * 0.00025f < 10.0f) {
            trigger_timer_warning_sound(&t);
            flailertext_set_color(TXT(o), COLOUR_LAP_WARNING);
        } else {
            flailertext_set_color(TXT(o), COLOUR_LAP_COUNTDOWN);
        }
    }
    print_time(&t, buf, 0);
    flailertext_set_string(TXT(o), buf);
}

// The running split and the comparison, 0x0017fa1c to 0x0017fcdc.
static void render_splits(struct Player *p, Race *race, struct RacingCar *rc)
{
    struct FlailerObjectChunk *run = p->pFlailerRunningSplitTime;
    struct FlailerObjectChunk *cmp = p->pFlailerCompSplitTime;
    int32_t i = (rc->HighestBoundaryRegion + 5) % 5;
    int32_t shown_run = 0, shown_cmp = 0;
    uint32_t x;
    char buf[16];

    if (i < 0)
        goto done;
    x = rc->BoundaryCrossingTimes[i].PackedTime;
    if (timer_word_valid(x)
        && (float)(int32_t)((uint32_t)WorldTimer - x) * 0.00025f < 5.0f
        && timer_word_valid(rc->RunningTimes[i].PackedTime)) {
        uint32_t t76 = rc->RunningTimes[i].PackedTime;
        Timer split;
        int ok = 0;

        print_time(&rc->RunningTimes[i], buf, 0);
        shown_run = 1;
        flailertext_set_string(TXT(run), buf);
        TXT(run)->FontHash = bchunk_hash("FONT_A");
        split.PackedTime = 0;
        switch (p->PlayerSettings.SplitTimeType) {
        case 0:
            // Against the leader, or the second when the player leads.
            if (rc != race->pRacingCars[0]) {
                race_calculate_split_time(race, &split, race->pRacingCars[0],
                                          rc);
                ok = 1;
            } else if (race->NumRacingCars >= 2
                       && race->pRacingCars[1] != NULL) {
                race_calculate_split_time(race, &split, race->pRacingCars[1],
                                          rc);
                ok = 1;
            }
            break;
        case 1:
            // Against the best lap, at the line only.
            if (i == 0
                && timer_word_valid(player_get_current_best_lap_record(p, 1))) {
                split.PackedTime = t76 - player_get_current_best_lap_record(p, 1);
                ok = 1;
            }
            break;
        case 2:
            if (timer_word_valid(rc->PreviousBestRunningTimes[i].PackedTime)) {
                split.PackedTime = t76
                    - rc->PreviousBestRunningTimes[i].PackedTime;
                ok = 1;
            }
            break;
        case 3:
            if (timer_word_valid(rc->PreviousRunningTimes[i].PackedTime)) {
                split.PackedTime = t76 - rc->PreviousRunningTimes[i].PackedTime;
                ok = 1;
            }
            break;
        }
        if (ok) {
            int print;

            shown_cmp = 1;
            if (cmp->Visibility != FLAILER_OBJECT_INVISIBLE)
                print = LiveUpdateSplitTimeRate != 0
                    && WorldLoopCounter % LiveUpdateSplitTimeRate == 0;
            else
                print = LiveUpdateSplitTimeRate != 0
                    || (float)(int32_t)((uint32_t)WorldTimer - x) * 0.00025f
                        < 0.2f;
            if (print) {
                print_time(&split, buf, TIMER_PRINT_SIGN);
                flailertext_set_string(TXT(cmp), buf);
            }
        }
    }
done:
    flailerobject_set_visibility(run, shown_run);
    flailerobject_set_visibility(cmp, shown_cmp);
}

// The driver's name, DriverInfo::GetName (0x00188770).
static const char *driver_name(const DriverInfo *d)
{
    if (d == NULL || d->pCharacterInfo == NULL)
        return "";
    return d->pCharacterInfo->CharacterName;
}

// Whether the car is pulled over: its CarPullovers entry's bActive, read
// by CarIndex as retail does, past the eight for a higher index.
static int car_pulled_over(const struct Car *c)
{
    int32_t idx = c->CarIndex;

    if (pCopManager == NULL || idx < 0 || idx >= 14)
        return 0;
    return copmanager_word(pCopManager, COPMANAGER_PULLOVERS
                           + (size_t)idx * sizeof(tCarPulloverInfo)
                           + offsetof(tCarPulloverInfo, bActive)) != 0;
}

// One row's status: the name, every 500 frames in turn with the car's,
// or the race's word on the car, or the gap to the player.
static void live_split_status(struct Player *p, Race *race,
                              struct RacingCar *rc, struct RacingCar *c,
                              struct FlailerObjectChunk *st)
{
    struct Car *car = c->pCar;
    char buf[16];

    if (WorldTimeFrames % 500 < 100
        || !timer_is_valid(racingcar_get_last_start_line_crossing_time(c))) {
        const char *s;

        if ((WorldTimeFrames / 500) & 1)
            s = hud_translate(car->pCarTypeInfo->pCarSpecs->ShortName);
        else if (c == rc)
            s = p->PlayerSettings.PlayerName;
        else
            s = driver_name(car->MyDriver);
        flailertext_set_string(TXT(st), s);
    } else if (c->FinishReason != 0) {
        flailertext_set_language_id(
            TXT(st), (uint32_t)racingcar_get_finish_reason_id(c->FinishReason));
    } else if (c == rc) {
        flailertext_set_string(TXT(st), p->PlayerSettings.PlayerName);
    } else if (car_pulled_over(car)) {
        flailertext_set_language_id(TXT(st), LANG_PULLED_OVER);
    } else {
        int32_t d = ee_trunc_w(c->CurrentLapNumberExact
                               - rc->CurrentLapNumberExact);

        if (d == 0) {
            Timer t;

            t.PackedTime = 0;
            race_calculate_split_time(race, &t, rc, c);
            print_time(&t, buf, TIMER_PRINT_SIGN);
            flailertext_set_string(TXT(st), buf);
            flailertext_set_format_options(TXT(st), BUI_FMT_FIXEDWIDTH);
            return;
        }
        flailer_printf_chunk(TXT(st), "%d %s", d,
                             hud_translate((d < 0 ? -d : d) == 1 ? LANG_LAP
                                                                 : LANG_LAPS));
    }
    flailertext_clear_format_options(TXT(st), BUI_FMT_FIXEDWIDTH);
}

// The live leaderboard's four rows, 0x0017fcec to 0x001800b4: the leader,
// then three from `start` on.
static void render_live_split(struct Player *p, Race *race,
                              struct RacingCar *rc)
{
    int32_t start = 2, i;

    if (TheRaceParameters.GlobalDisplaySettings.LeaderboardMode == 2) {
        int32_t s = rc->RacePosition - 1;

        if (race->NumRacingCars - 2 < s)
            s = race->NumRacingCars - 2;
        start = 1 < s ? s : 2;
    }
    for (i = 0; i < 4; i++) {
        int32_t n = i != 0 ? start + i - 1 : 1;
        struct FlailerObjectChunk *pos = p->pFlailerLiveSplitPos[i];
        struct FlailerObjectChunk *st = p->pFlailerLiveSplitStatus[i];
        struct FlailerObjectChunk *sw = p->pFlailerLiveSplitSwatch[i];
        struct FlailerObjectChunk *bg = p->pFlailerLiveSplitBG[i];
        struct RacingCar *c = NULL;
        const SkinInfo *skin;
        char num[2];

        if (n <= race->NumRacingCars && n - 1 < RACE_MAX_RACING_CARS)
            c = race->pRacingCars[n - 1];
        if (c == NULL || pos == NULL || st == NULL || sw == NULL
            || bg == NULL)
            continue;
        if (c == rc && p->pFlailerLiveSplitBar != NULL) {
            float x, y;

            flailerobject_get_top_left(bg, &x, &y);
            flailerobject_set_top_left_y(p->pFlailerLiveSplitBar, y);
            flailerobject_set_visibility(bg, 0);
        } else {
            flailerobject_set_visibility(bg, 1);
        }
        num[0] = (char)('0' + n);
        num[1] = '\0';
        flailertext_set_string(TXT(pos), num);
        skin = cartypeinfo_get_skin_info(c->pCar->pRideInfo->Type,
                                         c->pCar->pRideInfo->SkinNumber, 1);
        if (skin != NULL)
            flailerbitmap_change_texture(BMP(sw), skin->ColourSwatchHash);
        live_split_status(p, race, rc, c, st);
    }
}

// The lap counter, 0x001800cc to 0x00180190.
static void render_lap_counter(struct Player *p, Race *race,
                               struct RacingCar *rc)
{
    struct FlailerObjectChunk *o = p->pFlailerLapCounter;

    flailerobject_set_visibility(o, 1);
    if (TheRaceParameters.Point2Point != 0) {
        float x = race_get_lap_number_exact(
            race, race->BoundaryDistances[race->StartLineBoundaryNumber]);
        float pct = (rc->CurrentLapNumberExact - x) / (1.0f - x);

        if (pct < 0.0f)
            pct = 0.0f;
        if (1.0f < pct)
            pct = 1.0f;
        flailer_printf_chunk(TXT(o), "%5.1f %%", (double)(pct * 100.0f));
    } else {
        flailer_printf_chunk(TXT(o), "%d/%d", rc->NumLapsCompleted + 1,
                             race->NumLapsInRace);
    }
}

// The big race position, 0x001801e4 to 0x00180344.
static void render_race_position(struct Player *p, Race *race,
                                 struct RacingCar *rc)
{
    int32_t pos = rc->RacePosition;

    if (p->PositionFlag != 0) {
        p->PosChangeTime = (float)WorldTimer * 0.00025f;
        flailer_printf_chunk(TXT(p->pFlailerBigRacePosition2), "%d",
                             p->PositionFlag == 1 ? pos
                                                  : p->LastRacePosition);
        if (gHudStartGrowAnimationFn != NULL)
            gHudStartGrowAnimationFn(p, TXT(p->pFlailerBigRacePosition2),
                                     TXT(p->pFlailerBigRacePosition),
                                     (uint32_t)WorldTimer,
                                     pos < p->LastRacePosition);
    }
    p->LastRacePosition = pos;
    set_vis(p->pFlailerBigRacePosition, 1);
    set_vis(p->pFlailerBigRaceExtension, 1);
    set_vis(p->pFlailerBigRaceTotal, 1);
    flailer_printf_chunk(TXT(p->pFlailerBigRacePosition), "%d", pos);
    flailer_printf_chunk(TXT(p->pFlailerBigRaceTotal), "/%d",
                         TheRaceParameters.RaceType == RACE_TYPE_LAP_KNOCKOUT
                             ? race->NumRacingCars
                                   - race->NumRacingCarsFinished
                             : race->NumRacingCars);
    if (p->pFlailerBigRaceExtension != NULL) {
        flailertext_set_language_id(TXT(p->pFlailerBigRaceExtension),
                                    (uint32_t)(LANG_PLACE_1ST + pos));
        if (p->PlayerSettings.PreferredGender == 1 && pos == 1)
            flailertext_set_language_id(TXT(p->pFlailerBigRaceExtension),
                                        LANG_PLACE_1ST_F);
    }
}

// The tyres' grip, green to red, 0x00180368 to 0x00180414.
static void render_tyres(struct Player *p, struct Car *car)
{
    int i;

    for (i = 0; i < 4; i++) {
        float thr = 0.9f;
        float v;
        uint32_t c;

        if (0.999f < thr)
            thr = 0.999f;
        v = car->State.WheelTractionUsage[i];
        if (v < thr)
            c = (uint32_t)ee_trunc_w(v / thr * 255.0f) + COLOUR_TYRE_GRIP;
        else
            c = ((uint32_t)ee_trunc_w((1.0f - (v - thr) / (1.0f - thr))
                                      * 255.0f) << 8) + COLOUR_TYRE_SLIP;
        set_bitmap_colour(p->pFlailerTireForce[i], c);
    }
}

// The player cop's pursuit, if it is chasing.
static tPursuit *player_cop_pursuit(tCopManager *m)
{
    const tCopManagerHead *h = copmanager_head(m);
    tCop *cop;

    if (h->nPlayerCopIndex < 0 || h->nPlayerCopIndex >= 7)
        return NULL;
    cop = h->Cops[h->nPlayerCopIndex];
    return cop != NULL ? cop->pMyPursuit : NULL;
}

// 0x00224ec0, the port's name: a helicopter can be called while the World
// has one that is not out (its word at 960), the race allows it (New624)
// and the manager's bChopperBusy is clear.
static int can_call_helicopter(const tCopManager *m)
{
    const struct Chopper *heli = pCurrentWorld != NULL
        ? pCurrentWorld->Helicopter : NULL;
    int32_t out;

    if (heli == NULL || TheRaceParameters.New624 == 0)
        return 0;
    memcpy(&out, (const uint8_t *)heli + CHOPPER_NEW960, sizeof out);
    if (out != 0)
        return 0;
    return copmanager_word(m, COPMANAGER_CHOPPER_BUSY) == 0;
}

// Be The Cop's panel, 0x00180478 to 0x001808b0: the time left, the
// helicopters and roadblocks used, coming and left, the chased car's
// damage and the tickets given.
static void render_be_the_cop(struct Player *p, tCopManager *m)
{
    const tCopManagerHead *h = copmanager_head(m);
    float secs = copmanager_float(m, COPMANAGER_BEACOP_TIME);
    int32_t used, i, max, sum;
    tPursuit *pur;
    char buf[32];

    b_snprintf(buf, sizeof buf, 10.0f < secs ? "%3.0f" : "%3.1f",
             (double)secs);
    set_string(p->pFlailerBeTheCopTime, buf);

    // Retail's loops read past the three for a count over three; the
    // port's stop at three.
    used = copmanager_word(m, COPMANAGER_BEACOP_CHOPPERS);
    for (i = 0; i < used && i < 3; i++)
        set_bitmap_colour(p->pFlailerBeTheCopHelicopter[i], COLOUR_BTC_USED);
    if (i < used)
        i = used;
    if (!can_call_helicopter(m)) {
        if (i < 3)
            set_bitmap_colour(p->pFlailerBeTheCopHelicopter[i],
                              COLOUR_BTC_COMING);
        i++;
    }
    for (; i < 3; i++)
        set_bitmap_colour(p->pFlailerBeTheCopHelicopter[i], COLOUR_BTC_LEFT);

    used = h->nBeACopNumRoadBlocks;
    for (i = 0; i < used && i < 3; i++)
        set_bitmap_colour(p->pFlailerBeTheCopRoadblock[i], COLOUR_BTC_USED);
    if (i < used)
        i = used;
    pur = player_cop_pursuit(m);
    if (pur != NULL && pur->New1560 != 0) {
        if (i < 3)
            set_bitmap_colour(p->pFlailerBeTheCopRoadblock[i],
                              COLOUR_BTC_COMING);
        i++;
    }
    for (; i < 3; i++)
        set_bitmap_colour(p->pFlailerBeTheCopRoadblock[i], COLOUR_BTC_LEFT);

    if (p->MyCar != NULL) {
        float v = 0.0f;
        int32_t n;

        pur = player_cop_pursuit(m);
        if (pur != NULL && pur->pChasedCar != NULL) {
            int32_t idx = pur->pChasedCar->CarIndex;

            if (idx >= 0 && idx < 14)
                v = copmanager_float(m, COPMANAGER_CAR_DAMAGE
                                        + (size_t)idx * sizeof(float));
        }
        n = ee_trunc_w(v * 5.0f);
        if (v != 0.0f) {
            n++;
            if (!(n < 6))
                n = 5;
        }
        for (i = 0; i < n; i++)
            set_bitmap_colour(p->pFlailerDamageLight[i], COLOUR_DAMAGE_ON);
        for (; i < 5; i++)
            set_bitmap_colour(p->pFlailerDamageLight[i], COLOUR_DAMAGE_OFF);
    }

    // The tickets: the AI racers' in a race of one, else the other
    // player's.
    sum = 0;
    if (PlayerNumPlayers == 1) {
        World *w = pCurrentWorld;

        max = 4;
        for (i = 0; w != NULL && i < w->CopCarPos - w->AICarPos; i++) {
            struct Car *c = w->CarTable[w->AICarPos + i];

            if (c != NULL)
                sum += copmanager_get_num_tickets(m, c);
        }
    } else {
        struct Player *o = PlayerPlayersByIndex[1];

        max = 3;
        if (o != NULL && o->MyCar != NULL)
            sum = copmanager_get_num_tickets(m, o->MyCar);
    }
    for (i = 0; i < sum && i < 4; i++)
        set_vis(p->pFlailerBeTheCopTickets[i], 1);
    if (i < sum)
        i = sum;
    for (; i < max; i++)
        set_vis(p->pFlailerBeTheCopTickets[i], 0);
}

// The trackers over the AI racers and then the cops, 0x00180900 to
// 0x00180a94: every one hidden, then DrawTracker for each car drawn, the
// tracker's index the car's own in its block.
static void render_trackers(struct Player *p)
{
    World *w = pCurrentWorld;
    int32_t i, j;

    for (i = 0; i < 7; i++)
        set_vis(p->pFlailerTracker[i], 0);
    if (w == NULL)
        return;
    i = 0;
    j = 0;
    if (w->CopCarPos - w->AICarPos > 0) {
        do {
            struct Car *c = w->CarTable[w->AICarPos + i];

            if (c != NULL && c->RenderingEnabled != 0) {
                if (gDrawTrackerFn != NULL)
                    gDrawTrackerFn(p, c, j);
                set_bitmap_colour(p->pFlailerTracker[j], COLOUR_TRACK_RACER);
            }
            i++;
            j++;
        } while (i < w->CopCarPos - w->AICarPos && j < 7);
    }
    if (w->TrafficCarPos - w->CopCarPos > 0 && j < 7) {
        i = 0;
        do {
            struct Car *c = w->CarTable[w->CopCarPos + i];

            if (c != NULL && c->RenderingEnabled != 0) {
                if (gDrawTrackerFn != NULL)
                    gDrawTrackerFn(p, c, j);
                set_bitmap_colour(p->pFlailerTracker[j], COLOUR_TRACK_COP);
            }
            i++;
            j++;
        } while (i < w->TrafficCarPos - w->CopCarPos && j < 7);
    }
}

void player_render_hud(struct Player *p)
{
    Race *race = pCurrentRace;
    struct Car *car = p->MyCar;
    const CarTypeInfo *ti;
    struct RacingCar *rc;

    if (car == NULL)
        return;
    if (CameraFollowDefaultCar == 0) {
        struct Car *c = world_get_car_by_driver_number(
            CameraFollowThisCarInstead);

        if (c != NULL)
            car = c;
    }
    ti = p->MyCar->pCarTypeInfo;
    rc = race != NULL ? race_get_racing_car(race, car) : NULL;

    if (p->CurrentHudFeatures & HUD_ANY_GAUGE) {
        render_speed(p, car, ti);
        render_tach(p, car, ti);
    } else {
        p->LastSpeed = 999;
    }

    if ((p->CurrentHudFeatures & (HUD_LAP_TIME | HUD_LAP_COUNTER)) && rc != NULL
        && p->pFlailerLeadTitle != NULL)
        render_lead(p, race, rc);

    if ((p->CurrentHudFeatures & HUD_LAP_TIME) && rc != NULL
        && p->pFlailerLapTime != NULL)
        render_lap_time(p, rc);

    if ((p->CurrentHudFeatures & HUD_BEST_LAP) && p->pFlailerBestLap != NULL) {
        Timer t;
        char buf[16];

        t.PackedTime = player_get_current_best_lap_record(p, 0);
        if (timer_is_valid(&t)) {
            print_time(&t, buf, 0);
            flailertext_set_string(TXT(p->pFlailerBestLap), buf);
        } else {
            flailertext_set_string(TXT(p->pFlailerBestLap), "--:--:--");
        }
    }

    if ((p->CurrentHudFeatures & HUD_SPLIT_TIMES) && rc != NULL
        && p->pFlailerRunningSplitTime != NULL
        && p->pFlailerCompSplitTime != NULL)
        render_splits(p, race, rc);

    if ((p->CurrentHudFeatures & HUD_LIVE_SPLIT) && rc != NULL)
        render_live_split(p, race, rc);

    if (rc != NULL) {
        int32_t pos = rc->RacePosition;

        if ((p->CurrentHudFeatures & HUD_LAP_COUNTER)
            && p->pFlailerLapCounter != NULL)
            render_lap_counter(p, race, rc);
        if (p->LastRacePosition != pos) {
            p->PosChangeTime = (float)WorldTimer * 0.00025f;
            p->PositionFlag = pos < p->LastRacePosition ? 1 : -1;
        }
        p->LastRacePosition = pos;
        if ((p->CurrentHudFeatures & HUD_RACE_POSITION)
            && p->pFlailerBigRacePosition != NULL)
            render_race_position(p, race, rc);
    }

    if (p->CurrentHudFeatures & HUD_TIRE_FORCE)
        render_tyres(p, car);

    if (p->CurrentHudFeatures & (HUD_PURSUIT | HUD_PURSUIT_HI | HUD_PURSUIT_NIS)) {
        int32_t level = pCopManager != NULL
            ? copmanager_get_pursuit_level_for_hud(pCopManager, car) : 0;

        if (gUpdatePursuitMeterFn != NULL)
            gUpdatePursuitMeterFn(p, level);
    }
    if ((p->CurrentHudFeatures & HUD_RADAR) && gUpdateRadarDetectorFn != NULL)
        gUpdateRadarDetectorFn(p);

    if ((p->CurrentHudFeatures & HUD_BE_THE_COP) && pCopManager != NULL)
        render_be_the_cop(p, pCopManager);

    if ((p->CurrentHudFeatures & HUD_NIS_OVERLAY)
        && (player_is_nis_playing(p) || player_should_show_busted_text(p))
        && gNisOverlayUpdateFn != NULL)
        gNisOverlayUpdateFn(&p->mFlailerNIS, player_is_nis_playing(p) != 0);

    if ((p->CurrentHudFeatures & HUD_TRACKER) && race != NULL
        && race->RaceStage == RACE_STAGE_RACING) {
        render_trackers(p);
    } else {
        int i;

        for (i = 0; i < 7; i++)
            set_vis(p->pFlailerTracker[i], 0);
    }

    player_display_debug_info(p);
}

// ------------------------------------------------------------ UpdateHud

static void mark_place_reached(struct Player *p, int32_t i)
{
    if (i >= 0 && i < 8)
        p->baPlaceReached[i] = 1;
}

// 0x0017edb8 to 0x0017eeec: the places the player starts ahead of.
static void start_bonus(struct Player *p, Race *race)
{
    struct RacingCar *rc = p->MyCar != NULL
        ? race_get_racing_car(race, p->MyCar) : NULL;
    int32_t k;

    if (rc == NULL)
        return;
    if (PlayerNumPlayers == 2
        && race_parameters_num_eliminated(&TheRaceParameters) == 0) {
        int32_t n = race->NumRacingCars - 1;
        int32_t v = rc->RacePosition - 1;

        if (v == n)
            v = rc->RacePosition - 2;
        for (k = 0; k < n - v; k++)
            mark_place_reached(p, n - k - 1);
    } else {
        int32_t sum = 0;

        for (k = 0; k < race->NumRacingCars - rc->RacePosition; k++) {
            int32_t idx = race->NumRacingCars + 14 - k;

            if (idx >= 0 && idx < NUM_SCORE_INFOS)
                sum += player_convert_score_string(p,
                                                   ScoreInfoTable[idx].Score);
            mark_place_reached(p, race->NumRacingCars - 2 - k);
        }
        if (sum != 0) {
            b_snprintf(p->strEventScore, sizeof p->strEventScore, "+%d", sum);
            if (gStartScoreFn != NULL)
                gStartScoreFn(p, SCORING_START_BONUS, sum);
        }
    }
}

void player_update_hud(struct Player *p)
{
    Race *race = pCurrentRace;

    player_update_hud_features(p);
    if (gHudDoAnimationsFn != NULL)
        gHudDoAnimationsFn(p);
    player_fade_score(p);
    if (race != NULL && race->RaceStage == RACE_STAGE_RACING
        && pRaceCoordinator != NULL) {
        RCState s = pRaceCoordinator->CurrentRCState;

        if (s != RCSTATE_PAUSE && s != RCSTATE_INSTANT_REPLAY
            && s != RCSTATE_POSTRACE && s != RCSTATE_AUTO_REPLAY
            && s != RCSTATE_REPLAY_DEMO_MODE) {
            if (p->New2736 == 0) {
                start_bonus(p, race);
                p->New2736 = 1;
            }
            if (gUpdateScoringFn != NULL)
                gUpdateScoringFn(p);
        }
    }
    if (p->CurrentHudFeatures != 0)
        player_render_hud(p);
}
