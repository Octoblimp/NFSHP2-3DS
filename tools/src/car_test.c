// Transcript harness for the first Car slice. Cross-checked by
// tools/car_check.py, which models the same seventeen methods from the
// disassembly without reading this file or car.c.
//
// Every fixture float is its own decimal literal and none is computed from
// another: a sum rounds twice where a literal rounds once, and the fixtures
// are not the thing under test.
//
// The two world clocks are defined here rather than linked from engine.c,
// for the reason tools/src/drivetarget_test.c gives for the same pair:
// linking engine.c would drag Table, CarTypeInfo and Wheel in behind it, and
// the point of the harness is to exercise Car.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "car.h"

// car.h names CarDriver rather than including cardriver.h, to stay out of
// the cardriver.h -> drivetarget.h -> car.h cycle. This file declares one
// by value and reads Steering out of it, so it needs the complete record.
#include "cardriver.h"

int32_t WorldTimer = 0;
int32_t WorldTimeFrames = 0;

// The declarations car.c exports. Spelled here rather than pulled from a
// header so that a prototype drifting apart from a definition shows up as a
// compile error in this file and not as a silent reinterpretation.
void     car_fake_engine_task(Car *c);
void     car_event_handler(Car *c, void *event);
void     car_print_above(Car *c, const char *text, int colour);
void     car_start_blinking(Car *c, float duration);
void     car_stop_blinking(Car *c);
int32_t  car_is_blinking(Car *c);
void     car_blink_blink_poof(Car *c);
int32_t  car_is_poofed(Car *c);
int32_t  car_calculate_debug_checksum(Car *c);
float    car_get_wheels_on_ground(Car *c);
float    car_get_wheel_traction(Car *c);
int32_t  car_should_sound_effects_be_generated(Car *c);
int32_t  car_should_visual_effects_be_generated(Car *c);
float    car_get_forward_acceleration(Car *c);
void     car_honk_and_or_blink_headlights(Car *c, float onDuration,
                                          float offDuration, int32_t blink,
                                          int32_t honk, int32_t two);
void     car_turn_wipers_on_for_duration(Car *c, int32_t on, int32_t off);
uint16_t car_get_steering(Car *c);
void     car_world_to_car(Car *c, bVector2 *out, const bVector2 *in);

static Car        g_car;
static CarDriver  g_driver;
static DriverInfo g_info;

static void fresh(void)
{
    memset(&g_car, 0, sizeof g_car);
    memset(&g_driver, 0, sizeof g_driver);
    memset(&g_info, 0, sizeof g_info);
    g_car.pCarDriver = &g_driver;
    g_car.MyDriver = &g_info;
}

static void pf(const char *tag, float v)  { printf("  %-28s %.9g\n", tag, v); }
static void pi(const char *tag, int v)    { printf("  %-28s %d\n", tag, v); }

// --------------------------------------------------------------- layout

static void scenario_layout(void)
{
    printf("[layout]\n");
    pi("slack", (int)CAR_SLACK);
    pi("sizeof Car", (int)sizeof(Car));
    pi("sizeof CarNode", (int)sizeof(CarNode));
    pi("sizeof CarState", (int)sizeof(CarState));
    pi("sizeof TopologyCoordinate", (int)sizeof(TopologyCoordinate));
    pi("sizeof TrackPathCoordinate", (int)sizeof(TrackPathCoordinate));
    pi("sizeof OverrideRenderingPos", (int)sizeof(OverrideRenderingPosition));
    pi("sizeof DriverInfo", (int)sizeof(DriverInfo));
    pi("sizeof RideInfo", (int)sizeof(RideInfo));

    pi("off CarIndex", (int)offsetof(Car, CarIndex));
    pi("off DriverNumber", (int)offsetof(Car, DriverNumber));
    pi("off pCarTypeInfo", (int)offsetof(Car, pCarTypeInfo));
    pi("off MyDriver", (int)offsetof(Car, MyDriver));
    pi("off pPlayer", (int)offsetof(Car, pPlayer));
    pi("off TheControlMode", (int)offsetof(Car, TheControlMode));
    pi("off TheMovementMode", (int)offsetof(Car, TheMovementMode));
    pi("off pCarController", (int)offsetof(Car, pCarController));
    pi("off pCarDriver", (int)offsetof(Car, pCarDriver));
    pi("off pCarMover", (int)offsetof(Car, pCarMover));
    pi("off pDynamicCollisionBody", (int)offsetof(Car, pDynamicCollisionBody));
    pi("off State", (int)offsetof(Car, State));
    pi("off DispGear", (int)offsetof(Car, DispGear));
    pi("off FrictionBoost", (int)offsetof(Car, FrictionBoost));
    pi("off DraftFactor", (int)offsetof(Car, DraftFactor));
    pi("off vOldVel", (int)offsetof(Car, vOldVel));
    pi("off RenderingEnabled", (int)offsetof(Car, RenderingEnabled));
    pi("off pRenderInfo", (int)offsetof(Car, pRenderInfo));
    pi("off TheOverrideRendering", (int)offsetof(Car, TheOverrideRenderingPosition));
    pi("off TheTopologyCoordinate", (int)offsetof(Car, TheTopologyCoordinate));
    pi("off TheTrackPathCoordinate", (int)offsetof(Car, TheTrackPathCoordinate));
    pi("off CopLights", (int)offsetof(Car, CopLights));
    pi("off SignalLightState", (int)offsetof(Car, SignalLightState));
    pi("off HeadlightsAndHornStart", (int)offsetof(Car, HeadlightsAndHornStartTime));
    pi("off TheSirenMode", (int)offsetof(Car, TheSirenMode));
    pi("off WiperOnTime", (int)offsetof(Car, WiperOnTime));
    pi("off WiperOffTime", (int)offsetof(Car, WiperOffTime));
    pi("off WiperState", (int)offsetof(Car, WiperState));
    pi("off pCarDamage", (int)offsetof(Car, pCarDamage));
    pi("off BlownTireBits", (int)offsetof(Car, BlownTireBits));
    pi("off NumBlownTires", (int)offsetof(Car, NumBlownTires));
    pi("off pBaseCarSound", (int)offsetof(Car, pBaseCarSound));
    pi("off ResetMe", (int)offsetof(Car, ResetMe));
    pi("off BlinkTimer", (int)offsetof(Car, BlinkTimer));
    pi("off BlinkDuration", (int)offsetof(Car, BlinkDuration));
    pi("off LastInTroughPosition", (int)offsetof(Car, LastInTroughPosition));
    pi("off bPoofed", (int)offsetof(Car, bPoofed));
    pi("off bVisibleOnTrackMap", (int)offsetof(Car, bVisibleOnTrackMap));
    pi("off NumTimesSkidding", (int)offsetof(Car, NumTimesSkidding));
    pi("off RoadBumpBits", (int)offsetof(Car, RoadBumpBits));
    pi("off pCaffeineObj", (int)offsetof(Car, pCaffeineObj));
    pi("off LeaveCarTrails", (int)offsetof(Car, LeaveCarTrails));
    pi("off ForceBuzzTime", (int)offsetof(Car, ForceBuzzTime));
    pi("off fAngleToCamera", (int)offsetof(Car, fAngleToCamera));

    pi("off ORP GeometryPosition",
       (int)offsetof(OverrideRenderingPosition, GeometryPosition));
    pi("off ORP OverrideViewBits",
       (int)offsetof(OverrideRenderingPosition, OverrideViewBits));
    pi("off DriverInfo DriverType", (int)offsetof(DriverInfo, TheDriverType));
    pi("off DriverInfo RideInfo", (int)offsetof(DriverInfo, CurrentRideInfo));
    pi("off CarDriver Steering", (int)offsetof(CarDriver, Steering));

    pi("enum REAL_CONTROL", (int)REAL_CONTROL);
    pi("enum COP_CONTROL", (int)COP_CONTROL);
    pi("enum PHYSICS_MOVEMENT", (int)PHYSICS_MOVEMENT);
    pi("enum BELT_MOVEMENT", (int)BELT_MOVEMENT);
    pi("enum SIGNAL_LIGHT_ALL_ON", (int)SIGNAL_LIGHT_ALL_ON);
    pi("enum SIREN_MODE_BROKEN", (int)SIREN_MODE_BROKEN);
    pi("enum DRIVER_TYPE_TRAFFIC", (int)DRIVER_TYPE_TRAFFIC_CAR);
    pi("enum DRIVER_TYPE_SUPER_COP", (int)DRIVER_TYPE_SUPER_COP);
    pf("tick seconds", 0.000250000012f);
    {
        float t = 0.000250000012f;
        unsigned int w;
        memcpy(&w, &t, 4);
        printf("  %-28s %08x\n", "tick bits", w);
    }
    pi("wiper period", 82);
}

// ---------------------------------------------------------------- stubs

static void scenario_stubs(void)
{
    unsigned char before[sizeof(Car)], after[sizeof(Car)];
    size_t i, differ = 0;

    printf("[stubs]\n");
    fresh();
    // Values chosen so that a stub which secretly wrote a flag would
    // change one. A fixture holding the value the write would store is
    // a fixture that cannot see the write.
    g_car.BlinkTimer = 1234;
    g_car.bPoofed = 2;
    g_car.ResetMe = 2;
    g_car.NumTimesSkidding = 2;
    memcpy(before, &g_car, sizeof(Car));

    car_fake_engine_task(&g_car);
    car_event_handler(&g_car, (void *)0);
    car_print_above(&g_car, "ignored", 7);

    memcpy(after, &g_car, sizeof(Car));
    for (i = 0; i < sizeof(Car); i++)
        if (before[i] != after[i]) differ++;
    pi("bytes changed", (int)differ);
}

// -------------------------------------------------------------- blinking

static void scenario_blink(void)
{
    static const int32_t kNow[6] = {
        0, 1, 4000, 2147483647, -2147483648, -1
    };
    static const int32_t kStamp[7] = {
        0, 1, 2000, 2147483647, -2147483648, -1, 12345
    };
    static const float kDur[5] = {
        0.0f, 0.25f, 1.0f, 3.0f, -1.0f
    };
    int a, b, d;

    printf("[blink]\n");
    for (a = 0; a < 6; a++) {
        for (b = 0; b < 7; b++) {
            for (d = 0; d < 5; d++) {
                fresh();
                WorldTimer = kNow[a];
                g_car.BlinkTimer = kStamp[b];
                g_car.BlinkDuration = kDur[d];
                printf("  now %-12d stamp %-12d dur %-10.9g -> %d\n",
                       kNow[a], kStamp[b], kDur[d],
                       (int)car_is_blinking(&g_car));
            }
        }
    }

    printf("[blink start/stop]\n");
    for (a = 0; a < 6; a++) {
        fresh();
        WorldTimer = kNow[a];
        car_start_blinking(&g_car, 1.5f);
        printf("  start now %-12d timer %-12d dur %.9g blinking %d\n",
               kNow[a], (int)g_car.BlinkTimer, g_car.BlinkDuration,
               car_is_blinking(&g_car));
        car_stop_blinking(&g_car);
        printf("    after stop timer %d blinking %d\n",
               (int)g_car.BlinkTimer, car_is_blinking(&g_car));
    }

    printf("[blink poof]\n");
    for (a = 0; a < 6; a++) {
        fresh();
        WorldTimer = kNow[a];
        g_car.bVisibleOnTrackMap = 1;
        g_car.BlinkDuration = 99.0f;
        car_blink_blink_poof(&g_car);
        printf("  now %-12d timer %-12d dur %.9g map %d poofed %d\n",
               kNow[a], (int)g_car.BlinkTimer, g_car.BlinkDuration,
               (int)g_car.bVisibleOnTrackMap, (int)car_is_poofed(&g_car));
    }
}

// -------------------------------------------------------------- checksum

static void scenario_checksum(void)
{
    static const float kX[10] = {
        0.0f, 1.0f, -1.0f, 0.5f, -0.5f, 32767.5f, -32767.5f,
        0.0000152587890625f, 1e10f, -1e10f
    };
    static const float kY[10] = {
        0.0f, 2.0f, -2.0f, 0.25f, -0.25f, 0.5f, -0.5f,
        0.0000076293945312f, 1.0f, 1.0f
    };
    int i, j;

    printf("[checksum]\n");
    for (i = 0; i < 10; i++) {
        for (j = 0; j < 10; j++) {
            fresh();
            g_car.State.Position.x = kX[i];
            g_car.State.Position.y = kY[j];
            printf("  x %-18.9g y %-18.9g -> %d\n",
                   kX[i], kY[j], (int)car_calculate_debug_checksum(&g_car));
        }
    }
}

// The three conversion boundaries, by name rather than by printed float, so
// the label cannot drift with the host's %g. `hi` is exactly 2^31 after the
// scale and saturates; `lo` is exactly -2^31 and does not, because -2^31 is
// representable; `nan` is the arm that no EE float can reach -- see the note
// above car_trunc_w for why it is nonetheless there and tested.
static float bits_to_float(uint32_t u)
{
    float f;
    memcpy(&f, &u, sizeof f);
    return f;
}

static void scenario_checksum_edges(void)
{
    static const char *kName[6] = {
        "hi exactly 2^31", "hi one ulp under", "hi far over",
        "lo exactly -2^31", "lo one ulp under", "nan",
    };
    int i;

    printf("[checksum edges]\n");
    for (i = 0; i < 6; i++) {
        fresh();
        switch (i) {
        case 0: g_car.State.Position.x = 32768.0f;            break;
        case 1: g_car.State.Position.x = 32767.998046875f;    break;
        case 2: g_car.State.Position.x = 1e30f;               break;
        case 3: g_car.State.Position.x = -32768.0f;           break;
        case 4: g_car.State.Position.x = -32768.00390625f;    break;
        case 5: g_car.State.Position.x = bits_to_float(0x7fc00000u); break;
        }
        printf("  %-20s -> %d\n", kName[i],
               (int)car_calculate_debug_checksum(&g_car));
    }
}

// The tick constant, pinned to the bit.
//
// 4000 ticks times 0x3983126f is exactly 1.0f; times 0x3983126e --
// one ulp down, which is what a hand-typed 0.00024999999f gives -- it
// is 0.99999994f. Every other fixture in this file compares far enough
// from a boundary that both words give the same answer, so these two
// scenarios are the only thing standing between a mistyped tick and a
// clean transcript.
//
// IsBlinking's test is `elapsed < duration`, so a duration of exactly
// 1.0f answers no on the correct word and yes on the wrong one.
static void scenario_blink_tick(void)
{
    printf("[blink tick]\n");
    fresh();
    // 4001 - 1, not 4000 - 0: a stamp of 0 is the sentinel and would
    // early-out before the tick is ever multiplied in.
    WorldTimer = 4001;
    g_car.BlinkTimer = 1;
    g_car.BlinkDuration = 1.0f;
    printf("  dt 4000 dur 1 -> %d\n", (int)car_is_blinking(&g_car));
    g_car.BlinkDuration = 0.99999994f;
    printf("  dt 4000 dur 0.99999994 -> %d\n",
           (int)car_is_blinking(&g_car));
    WorldTimer = 0;
}

// HonkAndOrBlinkHeadlights' guard is `cycle < elapsed`, so a cycle of
// exactly 0.99999994f -- On + Off + On with On at zero -- fires on the
// correct word and does not fire on the wrong one. The opposite way
// round from the blink, and deliberately: the two call sites read the
// constant from different gp displacements in the image.
static void scenario_honk_tick(void)
{
    printf("[honk tick]\n");
    fresh();
    WorldTimer = 4000;
    g_car.HeadlightsAndHornStartTime = 0;
    g_car.HeadlightsAndHornOnDuration = 0.0f;
    g_car.HeadlightsAndHornOffDuration = 0.99999994f;
    car_honk_and_or_blink_headlights(&g_car, 0.75f, 0.125f, 1, 1, 1);
    printf("  cycle 0.99999994 -> honk %d on %.9g\n",
           (int)g_car.WantToHonkHorn,
           (double)g_car.HeadlightsAndHornOnDuration);
    WorldTimer = 0;
}

// -------------------------------------------------------- wheels on ground

static void scenario_wheels_on_ground(void)
{
    int mask;

    printf("[wheels on ground]\n");
    for (mask = 0; mask < 16; mask++) {
        int i;
        fresh();
        for (i = 0; i < 4; i++)
            g_car.State.WheelTouchingGround[i] =
                (int8_t)((mask >> i) & 1);
        printf("  mask %2d -> %.9g\n", mask,
               car_get_wheels_on_ground(&g_car));
    }

    // WheelTouchingGround is read with `lb`, so any non-zero byte counts and
    // the sign does not matter. -1 and 2 have to give the same answer as 1.
    printf("[wheels on ground non-bool]\n");
    {
        static const int8_t kVals[4] = { -1, 2, 127, -128 };
        int i;
        for (i = 0; i < 4; i++) {
            int k;
            fresh();
            for (k = 0; k < 4; k++)
                g_car.State.WheelTouchingGround[k] = kVals[i];
            printf("  all %-5d -> %.9g\n", (int)kVals[i],
                   car_get_wheels_on_ground(&g_car));
        }
    }
}

// -------------------------------------------------------- wheel traction

static void scenario_wheel_traction(void)
{
    // Four sets chosen so the two diagonals differ, and so reading the pairs
    // as axles instead gives a different answer on at least one of them.
    static const float kU[6][4] = {
        { 0.0f,  0.0f,  0.0f,  0.0f  },
        { 1.0f,  0.0f,  0.0f,  0.0f  },
        { 0.0f,  1.0f,  0.0f,  0.0f  },
        { 0.25f, 0.75f, 0.5f,  0.125f },
        { 1.0f,  0.5f,  0.5f,  0.0f  },
        { -1.0f, 0.5f,  0.25f, 2.0f  },
    };
    int i;

    printf("[wheel traction]\n");
    for (i = 0; i < 6; i++) {
        int k;
        fresh();
        for (k = 0; k < 4; k++)
            g_car.State.WheelTractionUsage[k] = kU[i][k];
        printf("  u %.9g %.9g %.9g %.9g -> %.9g\n",
               kU[i][0], kU[i][1], kU[i][2], kU[i][3],
               car_get_wheel_traction(&g_car));
    }
}

// ------------------------------------------------------------ the gates

static void scenario_effect_gates(void)
{
    static const int32_t kType[6] = { 0, 1, 2, 3, 4, 5 };
    int t, p, r;

    printf("[effect gates]\n");
    for (t = 0; t < 6; t++) {
        for (p = 0; p < 2; p++) {
            for (r = -1; r <= 1; r++) {
                fresh();
                g_info.TheDriverType = kType[t];
                g_car.bPoofed = p;
                g_car.RenderingEnabled = (int8_t)r;
                printf("  type %d poof %d render %-3d -> sound %d visual %d\n",
                       (int)kType[t], p, r,
                       (int)car_should_sound_effects_be_generated(&g_car),
                       (int)car_should_visual_effects_be_generated(&g_car));
            }
        }
    }
}

// ------------------------------------------------- forward acceleration

static void scenario_forward_acceleration(void)
{
    static const float kMag[7] = {
        0.0f, 0.0999999940395355f, 0.100000001490116f,
        0.100000008940697f, 1.0f, 50.0f, -5.0f
    };
    static const float kV[5][3] = {
        { 1.0f,  0.0f,  0.0f  },
        { 0.0f,  1.0f,  0.0f  },
        { 3.0f,  4.0f,  0.0f  },
        { -2.0f, 1.0f,  2.0f  },
        { 0.25f, 0.0f, -0.25f },
    };
    static const float kA[5][3] = {
        { 1.0f,  2.0f,  3.0f   },
        { -1.0f, 0.0f,  0.0f   },
        { 0.0f,  0.0f,  0.0f   },
        { 7.5f,  -2.5f, 0.125f },
        { -0.5f, -0.5f, -0.5f  },
    };
    int m, v, a;

    printf("[forward acceleration]\n");
    for (m = 0; m < 7; m++) {
        for (v = 0; v < 5; v++) {
            for (a = 0; a < 5; a++) {
                fresh();
                g_car.State.VelocityMagnitude = kMag[m];
                g_car.State.Velocity.x = kV[v][0];
                g_car.State.Velocity.y = kV[v][1];
                g_car.State.Velocity.z = kV[v][2];
                g_car.State.Acceleration.x = kA[a][0];
                g_car.State.Acceleration.y = kA[a][1];
                g_car.State.Acceleration.z = kA[a][2];
                printf("  mag %-20.9g v%d a%d -> %.9g\n",
                       kMag[m], v, a, car_get_forward_acceleration(&g_car));
            }
        }
    }
}

// ------------------------------------------------------- horn and lights

static void scenario_honk(void)
{
    static const int32_t kNow[4] = { 0, 4000, 40000, -1 };
    static const int32_t kStart[4] = { 0, 1000, 40000, -4000 };
    static const float kOldOn[3] = { 0.0f, 0.5f, 2.0f };
    static const float kOldOff[3] = { 0.0f, 0.25f, 1.0f };
    int n, s, a, b;

    printf("[honk]\n");
    for (n = 0; n < 4; n++) {
        for (s = 0; s < 4; s++) {
            for (a = 0; a < 3; a++) {
                for (b = 0; b < 3; b++) {
                    fresh();
                    WorldTimer = kNow[n];
                    g_car.HeadlightsAndHornStartTime = kStart[s];
                    g_car.HeadlightsAndHornOnDuration = kOldOn[a];
                    g_car.HeadlightsAndHornOffDuration = kOldOff[b];
                    car_honk_and_or_blink_headlights(&g_car, 0.75f, 0.125f,
                                                     1, 1, 1);
                    printf("  now %-12d start %-12d old %.9g %.9g\n",
                           kNow[n], kStart[s], kOldOn[a], kOldOff[b]);
                    printf("    -> start %-12d on %.9g off %.9g blink %d "
                           "honk %d two %d\n",
                           (int)g_car.HeadlightsAndHornStartTime,
                           g_car.HeadlightsAndHornOnDuration,
                           g_car.HeadlightsAndHornOffDuration,
                           (int)g_car.WantToBlinkHeadlights,
                           (int)g_car.WantToHonkHorn,
                           (int)g_car.WantTwoHonksAndOrBlinks);
                }
            }
        }
    }

    // The five request fields are written together or not at all, so a
    // dropped request has to leave every one of them alone -- including the
    // three flags, which a partial write would be easy to miss.
    printf("[honk drop]\n");
    fresh();
    WorldTimer = 0;
    g_car.HeadlightsAndHornStartTime = 0;
    g_car.HeadlightsAndHornOnDuration = 5.0f;
    g_car.HeadlightsAndHornOffDuration = 5.0f;
    g_car.WantToBlinkHeadlights = 9;
    g_car.WantToHonkHorn = 8;
    g_car.WantTwoHonksAndOrBlinks = 7;
    car_honk_and_or_blink_headlights(&g_car, 0.75f, 0.125f, 1, 1, 1);
    printf("  blink %d honk %d two %d on %.9g off %.9g start %d\n",
           (int)g_car.WantToBlinkHeadlights, (int)g_car.WantToHonkHorn,
           (int)g_car.WantTwoHonksAndOrBlinks,
           g_car.HeadlightsAndHornOnDuration,
           g_car.HeadlightsAndHornOffDuration,
           (int)g_car.HeadlightsAndHornStartTime);
}

// -------------------------------------------------------------- the wipers

static void scenario_wipers(void)
{
    static const int32_t kFrames[4] = { 0, 100, 500, -50 };
    static const int32_t kOnTime[5] = { 0, 50, 100, 300, 1000 };
    static const int32_t kOffTime[5] = { 0, 60, 200, 400, 900 };
    static const int32_t kReqOn[3] = { 20, 100, 600 };
    static const int32_t kReqOff[3] = { 80, 300, 700 };
    int f, a, b, c, d;

    printf("[wipers]\n");
    for (f = 0; f < 4; f++) {
        for (a = 0; a < 5; a++) {
            for (b = 0; b < 5; b++) {
                for (c = 0; c < 3; c++) {
                    for (d = 0; d < 3; d++) {
                        fresh();
                        WorldTimeFrames = kFrames[f];
                        g_car.WiperOnTime = (uint32_t)kOnTime[a];
                        g_car.WiperOffTime = (uint32_t)kOffTime[b];
                        car_turn_wipers_on_for_duration(&g_car, kReqOn[c],
                                                        kReqOff[d]);
                        printf("  f %-6d on %-6d off %-6d req %-5d %-5d "
                               "-> %d %d\n",
                               kFrames[f], kOnTime[a], kOffTime[b],
                               kReqOn[c], kReqOff[d],
                               (int)g_car.WiperOnTime,
                               (int)g_car.WiperOffTime);
                    }
                }
            }
        }
    }

    // WiperState non-zero drops the request entirely.
    printf("[wipers busy]\n");
    {
        static const int32_t kState[4] = { 1, -1, 2, 2147483647 };
        int i;
        for (i = 0; i < 4; i++) {
            fresh();
            WorldTimeFrames = 100;
            g_car.WiperState = kState[i];
            g_car.WiperOnTime = 7;
            g_car.WiperOffTime = 9;
            car_turn_wipers_on_for_duration(&g_car, 20, 80);
            printf("  state %-12d -> on %d off %d\n", (int)kState[i],
                   (int)g_car.WiperOnTime, (int)g_car.WiperOffTime);
        }
    }
}

// --------------------------------------------------------- world to car
//
// Car::WorldToCar is `j CarState::WorldToCar; addiu a0,a0,64`. The numbers
// belong to the CarState slice; what this scenario pins is the 64.
// MatrixValid is printed because it is the part that shows the offset: the
// transform sets it on whichever CarState it was handed.
static void scenario_world_to_car(void)
{
    static const int      kAng[6] = { 0, 0, 16384, 8192, 0, 49152 };
    static const float    kVx[6]  = { 0.0f, 0.0f, 0.0f, 0.0f, 3.0f, 0.0f };
    static const float    kVy[6]  = { 0.0f, 0.0f, 0.0f, 0.0f, 4.0f, 0.0f };
    static const float    kPx[6]  = { 0.0f, 10.0f, 0.0f, -3.0f, 0.0f, 100.0f };
    static const float    kPy[6]  = { 0.0f, -5.0f, 0.0f, 7.0f, 0.0f, 100.0f };
    static const float    kQx[6]  = { 1.0f, 12.5f, 1.0f, 0.5f, 1.0f, 99.0f };
    static const float    kQy[6]  = { 0.0f, -1.25f, 2.0f, 0.25f, 0.0f, 101.0f };
    int i;

    printf("[world to car]\n");
    for (i = 0; i < 6; i++) {
        bVector2 q, r;

        fresh();
        g_car.State.Angle = (uint16_t)kAng[i];
        g_car.State.Velocity.x = kVx[i];
        g_car.State.Velocity.y = kVy[i];
        g_car.State.Position.x = kPx[i];
        g_car.State.Position.y = kPy[i];
        g_car.State.ForwardSpeed = 1.0f;
        g_car.State.MatrixValid = 0;
        q.x = kQx[i];
        q.y = kQy[i];
        car_world_to_car(&g_car, &r, &q);
        printf("  ang %-6d pos %-8.9g %-8.9g q %-8.9g %-8.9g -> "
               "%-14.9g %-14.9g valid %d\n",
               kAng[i], (double)kPx[i], (double)kPy[i],
               (double)kQx[i], (double)kQy[i],
               (double)r.x, (double)r.y, (int)g_car.State.MatrixValid);
    }
}

// ------------------------------------------------------------- steering

static void scenario_steering(void)
{
    static const uint16_t kBam[8] = {
        0, 1, 16384, 32767, 32768, 49152, 65535, 12345
    };
    int i;

    printf("[steering]\n");
    for (i = 0; i < 8; i++) {
        fresh();
        g_driver.Steering = kBam[i];
        printf("  bam %-8u -> %u\n", (unsigned)kBam[i],
               (unsigned)car_get_steering(&g_car));
    }
}

int main(void)
{
    scenario_layout();
    scenario_stubs();
    scenario_blink();
    scenario_checksum();
    scenario_checksum_edges();
    scenario_blink_tick();
    scenario_honk_tick();
    scenario_wheels_on_ground();
    scenario_wheel_traction();
    scenario_effect_gates();
    scenario_forward_acceleration();
    scenario_honk();
    scenario_wipers();
    scenario_world_to_car();
    scenario_steering();
    return 0;
}
