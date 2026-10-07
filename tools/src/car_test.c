// Transcript harness for Car, slices one to three. Cross-checked by
// tools/car_check.py, which models the same methods from the disassembly
// without reading this file or car.c.
//
// Every fixture float is its own decimal literal and none is computed from
// another: a sum rounds twice where a literal rounds once, and the fixtures
// are not the thing under test.
//
// The two world clocks are defined here rather than linked from engine.c,
// for the reason tools/src/drivetarget_test.c gives for the same pair:
// linking engine.c would drag Table, CarTypeInfo and Wheel in behind it, and
// the point of the harness is to exercise Car.
//
// Slice two dispatches through vtables, so this file installs its own
// tables at the image's addresses (vtable.h) and fills them with functions
// that print what they were handed. What the transcript then shows is which
// slot each dispatcher took, with which `this`, and in which order -- the
// three things a virtual call can get wrong.
//
// Run with one argument, it instead drives one of vt_slot's refusals and
// prints "returned" if the refusal did not happen; car_check.py runs each
// mode and expects the process to abort.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "car.h"

// car.h names CarDriver rather than including cardriver.h, to stay out of
// the cardriver.h -> drivetarget.h -> car.h cycle. This file declares one
// by value and reads Steering out of it, so it needs the complete record.
#include "cardriver.h"
#include "sound3d.h"
#include "vtable.h"
#include "world.h"

int32_t WorldTimer = 0;
int32_t WorldTimeFrames = 0;

// car.h declares everything car.c exports, and car.c includes car.h, so a
// definition that drifts from its declaration is a compile error there. This
// file uses those declarations and repeats none of them.

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
    pi("off vOldPos", (int)offsetof(Car, vOldPos));
    pi("off SecondOnDuration",
       (int)offsetof(Car, HeadlightsAndHornSecondOnDuration));
    pi("off JustResetFrames", (int)offsetof(Car, JustResetFrames));
    pi("off InDeepWaterRegistered", (int)offsetof(Car, InDeepWaterRegistered));

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
    g_car.NumTimesSkidding[0] = 2;
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

// ===================================================================== slice 2

// ------------------------------------------------------- layout, continued

static void scenario_layout2(void)
{
    printf("[layout 2]\n");
    pi("sizeof CarController", (int)sizeof(CarController));
    pi("off CarController Driver", (int)offsetof(CarController, Driver));
    pi("off CarController vptr", (int)offsetof(CarController, _vtable));
    pi("off Tracked RoutePoint", (int)offsetof(TrackedController, RoutePoint));
    pi("off Tracked Acceleration",
       (int)offsetof(TrackedController, Acceleration));
    pi("off Tracked PrevSpeed", (int)offsetof(TrackedController, PrevSpeed));
    pi("off CarDriver vptr", (int)offsetof(CarDriver, _vtable));
    pi("sizeof Sound3d", (int)sizeof(Sound3d));
    pi("off Sound3d vptr", (int)offsetof(Sound3d, _vtable));
    pi("sizeof CollisionBody", (int)sizeof(CollisionBody));
    pi("off CollisionBody vptr", (int)offsetof(CollisionBody, _vtable));
    pi("sizeof DynamicCollisionBody", (int)sizeof(DynamicCollisionBody));
    pi("off Dynamic PhysicsMode",
       (int)offsetof(DynamicCollisionBody, PhysicsMode));
    pi("off Dynamic LocalBBMin", (int)offsetof(DynamicCollisionBody, LocalBBMin));
    pi("off Dynamic LocalBBMax", (int)offsetof(DynamicCollisionBody, LocalBBMax));
    pi("sizeof CarCollisionBody", (int)sizeof(CarCollisionBody));
    pi("off CarBody pCar", (int)offsetof(CarCollisionBody, pCar));
    pi("off CarBody LastPenetration",
       (int)offsetof(CarCollisionBody, LastPenetrationTime));
    pi("off CarBody LastYawControl",
       (int)offsetof(CarCollisionBody, LastYawControlCollisionTime));
    pi("off CarBody InertiaTensor",
       (int)offsetof(CarCollisionBody, ScaledInverseInertiaTensor));
    pi("sizeof Timer", (int)sizeof(Timer));
    pi("off World TotalNumCars", (int)offsetof(World, TotalNumCars));
    pi("off World CarTable", (int)offsetof(World, CarTable));
    pi("world max cars", WORLD_MAX_CARS);
    pi("off TRP Direction", (int)offsetof(TrackRoutePoint, Direction));
    pi("off CarState BodyMatrix", (int)offsetof(CarState, BodyMatrix));
    pi("off CarState VelocityMag", (int)offsetof(CarState, VelocityMagnitude));

    printf("  %-28s %08x\n", "vt CarController", CARCONTROLLER_VTABLE);
    printf("  %-28s %08x\n", "vt NullController", NULLCONTROLLER_VTABLE);
    printf("  %-28s %08x\n", "vt AICarController", AICARCONTROLLER_VTABLE);
    printf("  %-28s %08x\n", "vt RealController", REALCONTROLLER_VTABLE);
    printf("  %-28s %08x\n", "vt CarDriver", CARDRIVER_VTABLE);
    printf("  %-28s %08x\n", "vt NullDriver", NULLDRIVER_VTABLE);
    printf("  %-28s %08x\n", "vt BaseCarSound", BASECARSOUND_VTABLE);
    printf("  %-28s %08x\n", "vt BasePlayerCarSound", BASEPLAYERCARSOUND_VTABLE);
    printf("  %-28s %08x\n", "vt BaseAICarSound", BASEAICARSOUND_VTABLE);
    printf("  %-28s %08x\n", "vt CollisionBody", COLLISIONBODY_VTABLE);
    printf("  %-28s %08x\n", "vt DynamicCollisionBody",
           DYNAMICCOLLISIONBODY_VTABLE);
    printf("  %-28s %08x\n", "vt CarCollisionBody", CARCOLLISIONBODY_VTABLE);

    pi("slot Think", CARCONTROLLER_VT_THINK);
    pi("slot GetCurrentRoute", CARCONTROLLER_VT_GET_CURRENT_ROUTE);
    pi("slot GetCurrentRoutePoint", CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT);
    pi("slot GetAmountOutOfBounds", CARCONTROLLER_VT_GET_AMOUNT_OUT_OF_BOUNDS);
    pi("slot SetToPhysicsMode", CARCONTROLLER_VT_SET_TO_PHYSICS_MODE);
    pi("slot Drive", CARDRIVER_VT_DRIVE);
    pi("slot StartHonkHorn", CARDRIVER_VT_START_HONK_HORN);
    pi("slot StopHonkHorn", CARDRIVER_VT_STOP_HONK_HORN);
    pi("slot IsHonking", CARDRIVER_VT_IS_HONKING);
    pi("slot Sound3d Update", SOUND3D_VT_UPDATE);
    pi("slot AreCollisionsEnabled", COLLISIONBODY_VT_ARE_COLLISIONS_ENABLED);
    pi("vt slot 104", VT_SLOT(104));
}

// ------------------------------------------------------- the static tables

static uint32_t wbits(float f)
{
    uint32_t w;
    memcpy(&w, &f, 4);
    return w;
}

// Names an array the initialiser handed to a Graph or a Table, so the
// transcript shows *which* array was aliased rather than an address.
static const char *array_name(const void *p)
{
    if (p == (const void *)fDraftFalloff) return "fDraftFalloff";
    if (p == (const void *)vDraftSpeedRange) return "vDraftSpeedRange";
    if (p == (const void *)vRoadNoiseSpeedData) return "vRoadNoiseSpeedData";
    if (p == (const void *)PostCollisionYawControlProfileData)
        return "PostCollisionYawControlProfileData";
    return "?";
}

static int nonzero_bytes(const void *p, size_t n)
{
    const unsigned char *b = (const unsigned char *)p;
    int k = 0;
    size_t i;

    for (i = 0; i < n; i++)
        if (b[i]) k++;
    return k;
}

static void print_v2(const char *name, int i, const bVector2 *v)
{
    printf("  %s[%d] %08x %08x\n", name, i, wbits(v->x), wbits(v->y));
}

static void print_graph(const char *name, const Graph *g)
{
    printf("  %s points %s n %d\n", name, array_name(g->pPoints),
           (int)g->NumPoints);
}

static void scenario_static_init(void)
{
    int i, before;

    printf("[static init]\n");
    before = nonzero_bytes(vDraftSpeedRange, sizeof vDraftSpeedRange)
           + nonzero_bytes(&tDraftFalloff, sizeof tDraftFalloff)
           + nonzero_bytes(&gDraftSpeedRange, sizeof gDraftSpeedRange)
           + nonzero_bytes(vRoadNoiseSpeedData, sizeof vRoadNoiseSpeedData)
           + nonzero_bytes(&gRoadNoiseSpeedScale, sizeof gRoadNoiseSpeedScale)
           + nonzero_bytes(ObjectPoints, sizeof ObjectPoints)
           + nonzero_bytes(DamageAboveMatrix, sizeof DamageAboveMatrix)
           + nonzero_bytes(PostCollisionYawControlProfileData,
                           sizeof PostCollisionYawControlProfileData)
           + nonzero_bytes(&PostCollisionYawControlProfile,
                           sizeof PostCollisionYawControlProfile);
    pi("nonzero before init", before);

    car_static_init();

    for (i = 0; i < 6; i++)
        printf("  fDraftFalloff[%d] %08x\n", i, wbits(fDraftFalloff[i]));
    for (i = 0; i < 4; i++)
        print_v2("vDraftSpeedRange", i, &vDraftSpeedRange[i]);
    printf("  tDraftFalloff table %s n %d min %08x max %08x mult %08x\n",
           array_name(tDraftFalloff.pTable), (int)tDraftFalloff.NumEntries,
           wbits(tDraftFalloff.MinArg), wbits(tDraftFalloff.MaxArg),
           wbits(tDraftFalloff.IndexMultiplier));
    print_graph("gDraftSpeedRange", &gDraftSpeedRange);
    for (i = 0; i < 2; i++)
        print_v2("vRoadNoiseSpeedData", i, &vRoadNoiseSpeedData[i]);
    print_graph("gRoadNoiseSpeedScale", &gRoadNoiseSpeedScale);
    for (i = 0; i < 13; i++)
        printf("  ObjectPoints[%d] %08x %08x %08x %08x\n", i,
               wbits(ObjectPoints[i].x), wbits(ObjectPoints[i].y),
               wbits(ObjectPoints[i].z), wbits(ObjectPoints[i].pad));
    for (i = 0; i < 4; i++)
        printf("  DamageAboveMatrix[%d] %08x %08x %08x %08x\n", i,
               wbits(DamageAboveMatrix[i].x), wbits(DamageAboveMatrix[i].y),
               wbits(DamageAboveMatrix[i].z), wbits(DamageAboveMatrix[i].w));
    for (i = 0; i < 4; i++)
        print_v2("PostCollisionYawControlProfileData", i,
                 &PostCollisionYawControlProfileData[i]);
    print_graph("PostCollisionYawControlProfile",
                &PostCollisionYawControlProfile);
}

// ----------------------------------------------------------------- the draft

static Car   g_others[5];
static World g_world;

static void set_car(Car *k, float px, float py, float pz,
                    float vx, float vy, float vz, float speed)
{
    memset(k, 0, sizeof *k);
    k->State.Position.x = px;
    k->State.Position.y = py;
    k->State.Position.z = pz;
    k->State.Velocity.x = vx;
    k->State.Velocity.y = vy;
    k->State.Velocity.z = vz;
    k->State.VelocityMagnitude = speed;
}

static void print_draft(const char *tag, float r)
{
    printf("  %s -> %.9g %08x\n", tag, (double)r, wbits(r));
}

static void scenario_draft_from(void)
{
    // The slowest a leader can be and still give a draft is the knee at
    // vDraftSpeedRange[1].x, 1.0; the ulps either side are here.
    static const float kSpeed[9] = {
        0.5f, 0.99999994f, 1.0f, 1.00000012f, 3.0f, 5.0f, 100.0f, 150.0f,
        200.0f
    };
    // other - c, with c at the origin. 1.97 and 1.98 straddle the edge of
    // the cone for a leader six ahead travelling along +x, and 0.0197 and
    // 0.0198 the same edge a hundred times closer, where the falloff has
    // not yet reached zero; 59.9, 60 and 60.0001 straddle the distance cap.
    static const float kRel[15][3] = {
        { 12.0f,   0.0f,  0.0f }, {  0.0f, 12.0f,  0.0f },
        { -12.0f,  0.0f,  0.0f }, {  6.0f,  1.0f,  0.0f },
        {  6.0f,  1.97f,  0.0f }, {  6.0f,  1.98f, 0.0f },
        { 59.9f,   0.0f,  0.0f }, { 60.0f,  0.0f,  0.0f },
        { 60.0001f, 0.0f, 0.0f }, {  3.0f,  4.0f, 12.0f },
        {  0.001f, 0.0f,  0.0f }, { 30.0f,  0.0f, -2.5f },
        {  0.06f, 0.0197f, 0.0f }, {  0.06f, 0.0198f, 0.0f },
        {  1.5f,  2.0f,  0.0f },
    };
    // The fourth leader is reversing, so the car behind it along -x gets
    // the draft and the one ahead of it does not.
    static const float kVel[4][3] = {
        { 10.0f, 0.0f, 0.0f }, { 3.0f, 4.0f, 0.0f }, { 1.0f, 0.5f, 2.0f },
        { -10.0f, 0.0f, 0.0f },
    };
    // Absolute pairs, to see the subtraction's direction and that c's own
    // position is read rather than assumed to be the origin.
    static const float kPair[4][6] = {
        { 100.0f, -50.0f, 3.0f,  112.0f, -50.0f, 3.0f },
        { 112.0f, -50.0f, 3.0f,  100.0f, -50.0f, 3.0f },
        { -7.5f,   2.25f, 0.0f,   4.5f,   2.25f, 1.0f },
        { 1000.0f, 1000.0f, 0.0f, 1010.0f, 1005.0f, 0.0f },
    };
    int s, r, v;
    char tag[96];

    printf("[draft from]\n");
    for (s = 0; s < 9; s++) {
        for (r = 0; r < 15; r++) {
            for (v = 0; v < 4; v++) {
                fresh();
                set_car(&g_others[0], kRel[r][0], kRel[r][1], kRel[r][2],
                        kVel[v][0], kVel[v][1], kVel[v][2], kSpeed[s]);
                snprintf(tag, sizeof tag, "spd %.9g rel %d vel %d",
                         (double)kSpeed[s], r, v);
                print_draft(tag, car_calculate_draft_factor_from(
                                     &g_car, &g_others[0]));
            }
        }
    }

    printf("[draft pairs]\n");
    for (r = 0; r < 4; r++) {
        fresh();
        g_car.State.Position.x = kPair[r][0];
        g_car.State.Position.y = kPair[r][1];
        g_car.State.Position.z = kPair[r][2];
        // c's own velocity and speed are noise: only the leader's are read.
        g_car.State.Velocity.x = -3.0f;
        g_car.State.VelocityMagnitude = 0.25f;
        set_car(&g_others[0], kPair[r][3], kPair[r][4], kPair[r][5],
                10.0f, 0.0f, 0.0f, 120.0f);
        snprintf(tag, sizeof tag, "pair %d", r);
        print_draft(tag, car_calculate_draft_factor_from(&g_car,
                                                         &g_others[0]));
    }

    // Cases found by searching the model, each for the one rounding it
    // turns on. At the reach, the draft is nonzero only if dot / dist
    // rounds above 1 -- f then passes 1 and f * g passes 60 -- which no
    // single-axis velocity can do: sqrtf of a correctly rounded a * a is
    // |a| again. So the first two are diagonal: a leader exactly 60 away
    // with a sliver of draft, and one a few ulps past 60 with none, which
    // it would have if the reach were 150. The last two are the orders of
    // the velocity's length and of the dot, each case one where the other
    // grouping rounds differently.
    static const float kRound[4][7] = {
        { 35.793f, 32.2137f, 35.793f,   6.3f, 5.67f, 6.3f,  200.0f },
        { 47.6164f, 16.52f, -32.5541f,  9.8f, 3.4f, -6.7f,  200.0f },
        { 9.3f, 19.2f, 20.8f,           3.11f, 6.4f, 6.95f, 100.0f },
        { 18.5f, 4.0f, -1.25f,          9.0f, 2.0f, -0.75f, 100.0f },
    };

    printf("[draft rounding]\n");
    for (r = 0; r < 4; r++) {
        fresh();
        set_car(&g_others[0], kRound[r][0], kRound[r][1], kRound[r][2],
                kRound[r][3], kRound[r][4], kRound[r][5], kRound[r][6]);
        snprintf(tag, sizeof tag, "round %d", r);
        print_draft(tag, car_calculate_draft_factor_from(&g_car,
                                                         &g_others[0]));
    }
}

// The five leaders the world scenarios draw on, each travelling along +x
// at 200. Dead ahead of a car at the origin, 12 lands exactly on
// fDraftFalloff[1] and gives 0.9f to the bit; 24 gives 0.75f, 48 gives 0.3f
// and E, at 36, 0.55f. D is alongside and gives nothing.
static void set_leaders(void)
{
    set_car(&g_others[0], 12.0f, 0.0f, 0.0f, 10.0f, 0.0f, 0.0f, 200.0f);
    set_car(&g_others[1], 24.0f, 0.0f, 0.0f, 10.0f, 0.0f, 0.0f, 200.0f);
    set_car(&g_others[2], 48.0f, 0.0f, 0.0f, 10.0f, 0.0f, 0.0f, 200.0f);
    set_car(&g_others[3],  0.0f, 12.0f, 0.0f, 10.0f, 0.0f, 0.0f, 200.0f);
    set_car(&g_others[4], 36.0f, 0.0f, 0.0f, 10.0f, 0.0f, 0.0f, 200.0f);
}

// A world as a string: 'A' to 'E' are the leaders, 's' is the car itself
// and '0' is a null entry -- which the loop must never reach, because
// dereferencing it crashes the harness. `n` is TotalNumCars and may be
// shorter than the string, so the entry past the count is populated too.
static void set_world(const char *cars, int n)
{
    int i;

    memset(&g_world, 0, sizeof g_world);
    g_world.TotalNumCars = n;
    for (i = 0; cars[i]; i++) {
        switch (cars[i]) {
        case 's': g_world.CarTable[i] = &g_car; break;
        case '0': g_world.CarTable[i] = NULL; break;
        default:  g_world.CarTable[i] = &g_others[cars[i] - 'A']; break;
        }
    }
    pCurrentWorld = &g_world;
}

// "BB" and "CB" overshoot: the early-out breaks after the add that crossed
// 0.9, so only the cap brings them back to it. "CEC" stops at 0.85 on the
// way, which is under the early-out and so must not stop the loop.
static const char *const kWorld[15] = {
    "", "s", "C", "CD", "CsC", "CCC0", "A0", "BC0", "CCB", "DsD", "sA0",
    "CsCsC", "BB", "CB", "CEC"
};
static const int kWorldN[15] = { 0, 1, 1, 2, 3, 4, 2, 3, 2, 3, 3, 5, 2, 2, 3 };

static void scenario_draft_sum(void)
{
    int i;
    char tag[64];

    printf("[draft sum]\n");
    for (i = 0; i < 15; i++) {
        fresh();
        // c's own motion is not read by the sum -- unless it fails to skip
        // c, which then drafts from itself: past the knee, a 0 / 0.
        g_car.State.Velocity.x = 30.0f;
        g_car.State.VelocityMagnitude = 30.0f;
        set_leaders();
        set_world(kWorld[i], kWorldN[i]);
        snprintf(tag, sizeof tag, "world \"%s\" n %d", kWorld[i], kWorldN[i]);
        print_draft(tag, car_calculate_draft_factor(&g_car));
    }
    pCurrentWorld = NULL;
}

// ------------------------------------------------------------ the fakes

static CarController     g_ctl;
static TrackedController g_tctl;
static CarDriver         g_driver2;
static Sound3d           g_sound;
static CarCollisionBody  g_body;
static TrackRoute        g_route;
static TrackRoutePoint   g_rp;

static float   g_oob;
static int32_t g_enabled;
static int32_t g_honking;
static int     g_swap_driver;

typedef struct Fixture {
    const char *name;
    const void *base;
    size_t      size;
} Fixture;

// "<fixture>+<byte offset>" for whatever pointer a fake was handed. The
// dispatch adds the entry's delta to the object before the call, so the
// offset printed is the delta the call site applied.
static void name_of(const void *p, char *buf, size_t n)
{
    const Fixture k[] = {
        { "ctl",     &g_ctl,     sizeof g_ctl },
        { "tctl",    &g_tctl,    sizeof g_tctl },
        { "driver",  &g_driver,  sizeof g_driver },
        { "driver2", &g_driver2, sizeof g_driver2 },
        { "sound",   &g_sound,   sizeof g_sound },
        { "body",    &g_body,    sizeof g_body },
    };
    uintptr_t q = (uintptr_t)p;
    size_t i;

    for (i = 0; i < sizeof k / sizeof k[0]; i++) {
        uintptr_t b = (uintptr_t)k[i].base;
        if (q >= b && q < b + k[i].size) {
            snprintf(buf, n, "%s+%d", k[i].name, (int)(q - b));
            return;
        }
    }
    snprintf(buf, n, "?");
}

static void fk_think(void *self, float dt)
{
    char b[32];
    name_of(self, b, sizeof b);
    printf("    Think(%s, %.9g) sees draft %.9g\n", b, (double)dt,
           (double)g_car.DraftFactor);
}

static void fk_drive(void *self, float dt)
{
    char b[32];
    name_of(self, b, sizeof b);
    printf("    Drive(%s, %.9g)\n", b, (double)dt);
}

static TrackRoute *fk_route(void *self, int find)
{
    char b[32];
    (void)find;
    name_of(self, b, sizeof b);
    printf("    GetCurrentRoute(%s)\n", b);
    return &g_route;
}

static TrackRoutePoint *fk_route_point(void *self, int find)
{
    char b[32];
    (void)find;
    name_of(self, b, sizeof b);
    printf("    GetCurrentRoutePoint(%s)\n", b);
    return &g_rp;
}

static float fk_oob(void *self)
{
    char b[32];
    name_of(self, b, sizeof b);
    printf("    GetAmountOutOfBounds(%s)\n", b);
    return g_oob;
}

static void fk_update(void *self, float a, uint16_t s, float c)
{
    char b[32];
    name_of(self, b, sizeof b);
    printf("    Update(%s, %.9g, %u, %.9g)\n", b, (double)a, (unsigned)s,
           (double)c);
}

static int32_t fk_enabled(void *self)
{
    char b[32];
    name_of(self, b, sizeof b);
    printf("    AreCollisionsEnabled(%s) = %d\n", b, (int)g_enabled);
    return g_enabled;
}

// Hands the car a different driver when asked to, so the transcript shows
// whether the second call of the pair reloads pCarDriver or reuses the one
// the first call went through.
static int32_t fk_is_honking(void *self)
{
    char b[32];
    name_of(self, b, sizeof b);
    printf("    IsHonking(%s) = %d\n", b, (int)g_honking);
    if (g_swap_driver)
        g_car.pCarDriver = &g_driver2;
    return g_honking;
}

static void fk_start_honk(void *self)
{
    char b[32];
    name_of(self, b, sizeof b);
    printf("    StartHonkHorn(%s)\n", b);
}

static void fk_stop_honk(void *self)
{
    char b[32];
    name_of(self, b, sizeof b);
    printf("    StopHonkHorn(%s)\n", b);
}

// One table per (class, delta) pair. The controller and driver tables run
// to +104, entry 13; the sound's to +24; the body's to +136.
static VtEntry t_ctl0[14], t_ctl4[14], t_drv0[14], t_drv8[14];
static VtEntry t_snd0[4], t_snd4[4], t_body0[18], t_body12[18];

static void put(VtEntry *t, int slot, int delta, VtFn fn)
{
    t[VT_SLOT(slot)].delta = (int16_t)delta;
    t[VT_SLOT(slot)].index = 0;
    t[VT_SLOT(slot)].fn = fn;
}

static void fill_ctl(VtEntry *t, int d)
{
    memset(t, 0, 14 * sizeof *t);
    put(t, CARCONTROLLER_VT_THINK, d, (VtFn)fk_think);
    put(t, CARCONTROLLER_VT_GET_CURRENT_ROUTE, d, (VtFn)fk_route);
    put(t, CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT, d, (VtFn)fk_route_point);
    put(t, CARCONTROLLER_VT_GET_AMOUNT_OUT_OF_BOUNDS, d, (VtFn)fk_oob);
}

static void fill_drv(VtEntry *t, int d)
{
    memset(t, 0, 14 * sizeof *t);
    put(t, CARDRIVER_VT_DRIVE, d, (VtFn)fk_drive);
    put(t, CARDRIVER_VT_START_HONK_HORN, d, (VtFn)fk_start_honk);
    put(t, CARDRIVER_VT_STOP_HONK_HORN, d, (VtFn)fk_stop_honk);
    put(t, CARDRIVER_VT_IS_HONKING, d, (VtFn)fk_is_honking);
}

static void install_fakes(void)
{
    vt_reset();

    fill_ctl(t_ctl0, 0);
    fill_ctl(t_ctl4, 4);
    vt_install(REALCONTROLLER_VTABLE, t_ctl0, 14);
    vt_install(AICARCONTROLLER_VTABLE, t_ctl4, 14);

    fill_drv(t_drv0, 0);
    fill_drv(t_drv8, 8);
    vt_install(NULLDRIVER_VTABLE, t_drv0, 14);
    vt_install(CARDRIVER_VTABLE, t_drv8, 14);

    memset(t_snd0, 0, sizeof t_snd0);
    memset(t_snd4, 0, sizeof t_snd4);
    put(t_snd0, SOUND3D_VT_UPDATE, 0, (VtFn)fk_update);
    put(t_snd4, SOUND3D_VT_UPDATE, 4, (VtFn)fk_update);
    vt_install(BASECARSOUND_VTABLE, t_snd0, 4);
    vt_install(BASEAICARSOUND_VTABLE, t_snd4, 4);

    memset(t_body0, 0, sizeof t_body0);
    memset(t_body12, 0, sizeof t_body12);
    put(t_body0, COLLISIONBODY_VT_ARE_COLLISIONS_ENABLED, 0, (VtFn)fk_enabled);
    put(t_body12, COLLISIONBODY_VT_ARE_COLLISIONS_ENABLED, 12,
        (VtFn)fk_enabled);
    vt_install(CARCOLLISIONBODY_VTABLE, t_body0, 18);
    vt_install(DYNAMICCOLLISIONBODY_VTABLE, t_body12, 18);
}

// fresh() plus every object slice two dispatches to, each carrying the
// delta-0 table unless a scenario swaps it.
static void fresh2(void)
{
    fresh();
    memset(&g_ctl, 0, sizeof g_ctl);
    memset(&g_tctl, 0, sizeof g_tctl);
    memset(&g_driver2, 0, sizeof g_driver2);
    memset(&g_sound, 0, sizeof g_sound);
    memset(&g_body, 0, sizeof g_body);
    memset(&g_rp, 0, sizeof g_rp);
    g_ctl._vtable = REALCONTROLLER_VTABLE;
    g_driver._vtable = NULLDRIVER_VTABLE;
    g_driver2._vtable = CARDRIVER_VTABLE;
    g_sound._vtable = BASECARSOUND_VTABLE;
    g_body.Dynamic.Body._vtable = CARCOLLISIONBODY_VTABLE;
    g_car.pCarController = &g_ctl;
    g_car.pBaseCarSound = (BaseCarSound *)&g_sound;
    g_car.pDynamicCollisionBody = &g_body;
    g_oob = 0.0f;
    g_enabled = 0;
    g_honking = 0;
    g_swap_driver = 0;
}

// ------------------------------------------------------------ the vtable seam

static int g_mark;
static void fk_mark_a(void) { g_mark = 1; }
static void fk_mark_b(void) { g_mark = 2; }
static void fk_mark_c(void) { g_mark = 3; }

static int dispatch_mark(uint32_t image, int slot, int *delta)
{
    const VtEntry *e = vt_slot(image, slot);
    g_mark = 0;
    e->fn();
    *delta = e->delta;
    return g_mark;
}

static void scenario_vtable(void)
{
    static VtEntry a[3], b[3], c[3];
    int d, m;

    printf("[vtable]\n");
    vt_reset();
    memset(a, 0, sizeof a);
    memset(b, 0, sizeof b);
    memset(c, 0, sizeof c);
    a[1].fn = (VtFn)fk_mark_a; a[2].fn = (VtFn)fk_mark_a; a[2].delta = -8;
    b[1].fn = (VtFn)fk_mark_b; b[2].fn = (VtFn)fk_mark_b; b[2].delta = 16;
    c[1].fn = (VtFn)fk_mark_c;

    vt_install(0x00111110u, a, 3);
    m = dispatch_mark(0x00111110u, 8, &d);
    printf("  X+8 -> %d delta %d\n", m, d);
    m = dispatch_mark(0x00111110u, 16, &d);
    printf("  X+16 -> %d delta %d\n", m, d);

    // Installing the same address again replaces its entries rather than
    // adding a second registration behind the first.
    vt_install(0x00111110u, b, 3);
    m = dispatch_mark(0x00111110u, 8, &d);
    printf("  X+8 after replace -> %d delta %d\n", m, d);
    m = dispatch_mark(0x00111110u, 16, &d);
    printf("  X+16 after replace -> %d delta %d\n", m, d);

    vt_install(0x00222220u, c, 2);
    m = dispatch_mark(0x00222220u, 8, &d);
    printf("  Y+8 -> %d delta %d\n", m, d);
    m = dispatch_mark(0x00111110u, 8, &d);
    printf("  X+8 beside Y -> %d delta %d\n", m, d);

    // vt_this is `obj + delta` in bytes, whatever obj's type.
    {
        VtEntry e;
        char buf[64];
        e.delta = -8; e.index = 0; e.fn = NULL;
        printf("  this -8 -> %d\n", (int)((char *)vt_this(buf + 32, &e) - buf));
        e.delta = 24;
        printf("  this +24 -> %d\n", (int)((char *)vt_this(buf + 32, &e) - buf));
    }
    vt_reset();
}

// Each mode is one refusal. The table has a sixth entry past its count and a
// live function in entry 0, so a vt_slot that forgot a bound would find
// something callable and return rather than abort.
static int abort_mode(const char *m)
{
    static VtEntry t[6];
    const uint32_t A = 0x00123450u;
    int i;

    for (i = 0; i < 6; i++) {
        t[i].delta = 0;
        t[i].index = 0;
        t[i].fn = (VtFn)fk_mark_a;
    }
    vt_reset();

    if (!strcmp(m, "vt-missing")) {
        vt_slot(A, 8);
    } else if (!strcmp(m, "vt-reset")) {
        vt_install(A, t, 5);
        vt_reset();
        vt_slot(A, 8);
    } else if (!strcmp(m, "vt-misaligned")) {
        vt_install(A, t, 5);
        vt_slot(A, 12);
    } else if (!strcmp(m, "vt-slot-zero")) {
        vt_install(A, t, 5);
        vt_slot(A, 0);
    } else if (!strcmp(m, "vt-negative")) {
        vt_install(A, t, 5);
        vt_slot(A, -8);
    } else if (!strcmp(m, "vt-past-end")) {
        vt_install(A, t, 5);
        vt_slot(A, 40);
    } else if (!strcmp(m, "vt-null-fn")) {
        t[2].fn = NULL;
        vt_install(A, t, 5);
        vt_slot(A, 16);
    } else if (!strcmp(m, "vt-full")) {
        // Ninety-six fit. The count goes out before the ninety-seventh,
        // flushed, because abort() does not flush stdio.
        for (i = 0; i < 96; i++)
            vt_install(0x00100000u + 8u * (uint32_t)i, t, 5);
        printf("%d installed\n", i);
        fflush(stdout);
        vt_install(0x00100000u + 8u * 96u, t, 5);
    } else {
        printf("unknown mode %s\n", m);
        return 2;
    }
    printf("returned\n");
    return 0;
}

// ------------------------------------------------------------- dispatchers

static void scenario_think(void)
{
    static const float kDt[3] = { 0.0166666675f, 0.0f, -0.5f };
    static const uint32_t kVt[2] = { REALCONTROLLER_VTABLE,
                                     AICARCONTROLLER_VTABLE };
    int v, d, w;

    printf("[think]\n");
    for (w = 0; w < 3; w++) {
        for (v = 0; v < 2; v++) {
            for (d = 0; d < 3; d++) {
                fresh2();
                set_leaders();
                // "C", "BC0" and an empty world: 0.3, the cap, and 0.
                set_world(w == 0 ? "C" : w == 1 ? "BC0" : "", w == 2 ? 0
                          : w == 1 ? 3 : 1);
                g_car.DraftFactor = 7.0f;
                g_ctl._vtable = kVt[v];
                printf("  world %d vt %d dt %.9g\n", w, v, (double)kDt[d]);
                car_think(&g_car, kDt[d]);
                printf("    after draft %.9g\n", (double)g_car.DraftFactor);
            }
        }
    }
    pCurrentWorld = NULL;
}

static void scenario_drive(void)
{
    static const float kDt[2] = { 0.0333333351f, 2.5f };
    int v, d;

    printf("[drive]\n");
    for (v = 0; v < 2; v++) {
        for (d = 0; d < 2; d++) {
            fresh2();
            if (v)
                g_car.pCarDriver = &g_driver2;
            printf("  driver %d dt %.9g\n", v, (double)kDt[d]);
            car_drive(&g_car, kDt[d]);
        }
    }
}

static void scenario_route(void)
{
    static const float kOob[3] = { 0.0f, -2.5f, 1e30f };
    int v, o;

    printf("[route]\n");
    for (v = 0; v < 2; v++) {
        fresh2();
        g_ctl._vtable = v ? AICARCONTROLLER_VTABLE : REALCONTROLLER_VTABLE;
        printf("  vt %d\n", v);
        printf("    route is g_route %d\n", car_get_route(&g_car, 1) == &g_route);
        printf("    point is g_rp %d\n", car_get_route_point(&g_car, 1) == &g_rp);
        for (o = 0; o < 3; o++) {
            g_oob = kOob[o];
            printf("    oob %.9g\n", (double)car_get_amount_out_of_bounds(&g_car));
        }
    }
}

static void scenario_sound(void)
{
    int v;

    printf("[sound]\n");
    fresh2();
    g_car.pBaseCarSound = NULL;
    printf("  no sound\n");
    car_update_sound(&g_car);
    for (v = 0; v < 2; v++) {
        fresh2();
        g_sound._vtable = v ? BASEAICARSOUND_VTABLE : BASECARSOUND_VTABLE;
        // Fields a wrong-offset read would pick up instead of the vptr.
        g_sound.Volume = 0.5f;
        g_sound.Pitch = 2.0f;
        printf("  vt %d\n", v);
        car_update_sound(&g_car);
    }
}

static void scenario_collideable(void)
{
    static const int32_t kAnswer[4] = { 0, 1, 2, -1 };
    int b, a, v;

    printf("[collideable]\n");
    for (b = 0; b < 3; b++) {
        for (v = 0; v < 2; v++) {
            for (a = 0; a < 4; a++) {
                fresh2();
                // Not blinking; blinking for the next second; a blink that
                // has run out.
                WorldTimer = 10000;
                if (b == 1) {
                    g_car.BlinkTimer = 9000;
                    g_car.BlinkDuration = 1.0f;
                } else if (b == 2) {
                    g_car.BlinkTimer = 1000;
                    g_car.BlinkDuration = 1.0f;
                }
                g_body.Dynamic.Body._vtable =
                    v ? DYNAMICCOLLISIONBODY_VTABLE : CARCOLLISIONBODY_VTABLE;
                g_enabled = kAnswer[a];
                printf("  blink %d vt %d answer %d\n", b, v, (int)kAnswer[a]);
                printf("    -> %d\n", (int)car_is_collideable(&g_car));
            }
        }
    }
    WorldTimer = 0;
}

static void scenario_wrong_way(void)
{
    static const float kFwd[7][2] = {
        { 1.0f, 0.0f }, { 0.0f, 1.0f }, { -1.0f, 0.0f }, { 0.6f, 0.8f },
        { 1e-20f, 0.0f }, { -0.6f, 0.8f }, { 0.0f, -1.0f },
    };
    static const float kDir[5][2] = {
        { 1.0f, 0.0f }, { 0.0f, 1.0f }, { -1.0f, 0.0f }, { 0.0f, -1.0f },
        { 0.6f, -0.8f },
    };
    int f, d;

    printf("[wrong way]\n");
    for (f = 0; f < 7; f++) {
        for (d = 0; d < 5; d++) {
            fresh2();
            g_car.State.BodyMatrix.v0.x = kFwd[f][0];
            g_car.State.BodyMatrix.v0.y = kFwd[f][1];
            // Everything else the test must not read: the forward axis's
            // z, the side axis, and the route point's own position.
            g_car.State.BodyMatrix.v0.z = -100.0f;
            g_car.State.BodyMatrix.v1.x = -kFwd[f][1];
            g_car.State.BodyMatrix.v1.y = kFwd[f][0];
            g_rp.Position.x = 5.0f;
            g_rp.Position.y = -5.0f;
            g_rp.Direction.x = kDir[d][0];
            g_rp.Direction.y = kDir[d][1];
            printf("  fwd %d dir %d\n", f, d);
            printf("    -> %d\n", (int)car_is_facing_wrong_way(&g_car));
        }
    }
}

static void scenario_headlights(void)
{
    // Ticks since the stamp, with on 0.5 s and off 0.25 s: inside the first
    // on phase, both edges of the gap, the second on phase and its end, and
    // a clock behind the stamp.
    static const int32_t kTicks[9] = {
        0, 1000, 2000, 2500, 3000, 4000, 5000, 8000, -400
    };
    static const int32_t kHonk[2] = { 0, 5 };
    static const int32_t kIs[2] = { 0, 3 };
    int t, two, bl, h, fo, is;

    printf("[headlights]\n");
    for (t = 0; t < 9; t++)
    for (two = 0; two < 2; two++)
    for (bl = 0; bl < 2; bl++)
    for (h = 0; h < 2; h++)
    for (fo = 0; fo < 2; fo++)
    for (is = 0; is < 2; is++) {
        fresh2();
        WorldTimer = 50000 + kTicks[t];
        g_car.HeadlightsAndHornStartTime = 50000;
        g_car.HeadlightsAndHornOnDuration = 0.5f;
        g_car.HeadlightsAndHornOffDuration = 0.25f;
        g_car.WantTwoHonksAndOrBlinks = two;
        g_car.WantToBlinkHeadlights = bl ? 7 : 0;
        g_car.WantToHonkHorn = kHonk[h];
        g_car.ForceHeadlightsOn = fo ? 2 : 0;
        g_car.HeadlightsState = 9;
        g_honking = kIs[is];
        printf("  t %d two %d blink %d honk %d force %d is %d\n",
               (int)kTicks[t], two, bl, (int)kHonk[h], fo, (int)kIs[is]);
        car_update_headlights_and_horn(&g_car);
        printf("    lights %d\n", (int)g_car.HeadlightsState);
    }

    // A player's car is left entirely alone: no lights, no calls.
    printf("[headlights player]\n");
    fresh2();
    g_car.pPlayer = (Player *)&g_others[0];
    g_car.WantToBlinkHeadlights = 1;
    g_car.WantToHonkHorn = 1;
    g_car.HeadlightsAndHornOnDuration = 5.0f;
    g_car.HeadlightsState = 9;
    car_update_headlights_and_horn(&g_car);
    printf("  lights %d\n", (int)g_car.HeadlightsState);

    // IsHonking hands the car driver2, whose table carries a delta of 8:
    // the Start or Stop that follows must go to driver2+8.
    printf("[headlights reload]\n");
    WorldTimer = 0;
    for (h = 0; h < 2; h++) {
        fresh2();
        g_car.HeadlightsAndHornOnDuration = 1.0f;
        g_car.WantToHonkHorn = h;
        g_honking = !h;
        g_swap_driver = 1;
        printf("  honk %d\n", h);
        car_update_headlights_and_horn(&g_car);
    }
    WorldTimer = 0;
}

// --------------------------------------------------- borrowed fields again

static void print_v3w(const char *tag, const bVector3 *v)
{
    printf("  %s %08x %08x %08x %08x\n", tag, wbits(v->x), wbits(v->y),
           wbits(v->z), wbits(v->pad));
}

static void set_bbox(void)
{
    g_body.Dynamic.LocalBBMin.x = -1.5f;
    g_body.Dynamic.LocalBBMin.y = -2.5f;
    g_body.Dynamic.LocalBBMin.z = -0.25f;
    g_body.Dynamic.LocalBBMin.pad = 11.0f;
    g_body.Dynamic.LocalBBMax.x = 1.5f;
    g_body.Dynamic.LocalBBMax.y = 2.5f;
    g_body.Dynamic.LocalBBMax.z = 1.75f;
    g_body.Dynamic.LocalBBMax.pad = -13.0f;
    // The two neighbours of the box, so an off-by-a-field read shows.
    g_body.Dynamic.Radius = 99.0f;
    g_body.pCar = NULL;
}

static void scenario_bbox(void)
{
    bVector3 lo, hi;

    printf("[bbox]\n");
    fresh2();
    set_bbox();
    memset(&lo, 0, sizeof lo);
    memset(&hi, 0, sizeof hi);
    car_get_car_space_bounding_box(&g_car, &lo, &hi);
    print_v3w("min", &lo);
    print_v3w("max", &hi);

    // min is the body's own LocalBBMax: written before max reads it.
    printf("[bbox alias max]\n");
    fresh2();
    set_bbox();
    memset(&hi, 0, sizeof hi);
    car_get_car_space_bounding_box(&g_car, &g_body.Dynamic.LocalBBMax, &hi);
    print_v3w("max out", &hi);
    print_v3w("body max", &g_body.Dynamic.LocalBBMax);

    // max is the body's own LocalBBMin: min has already read it.
    printf("[bbox alias min]\n");
    fresh2();
    set_bbox();
    memset(&lo, 0, sizeof lo);
    car_get_car_space_bounding_box(&g_car, &lo, &g_body.Dynamic.LocalBBMin);
    print_v3w("min out", &lo);
    print_v3w("body min", &g_body.Dynamic.LocalBBMin);
}

static void scenario_penetration(void)
{
    static const uint32_t kWord[4] = { 0u, 1u, 0xdeadbeefu, 0x80000000u };
    int i;

    printf("[penetration]\n");
    for (i = 0; i < 4; i++) {
        Timer t;
        fresh2();
        g_body.LastPenetrationTime.PackedTime = kWord[i];
        g_body.LastYawControlCollisionTime.PackedTime = 0x5a5a5a5au;
        g_body.pCar = &g_car;
        t = car_get_last_penetration_time(&g_car);
        printf("  word %08x -> %08x\n", (unsigned)kWord[i],
               (unsigned)t.PackedTime);
    }
}

static void scenario_tracked(void)
{
    static const int32_t kMode[7] = { -1, 0, 1, 2, 3, 4, 5 };
    static const float kAcc[2] = { 3.5f, -0.0f };
    int m, a;

    printf("[tracked acceleration]\n");
    for (m = 0; m < 7; m++) {
        for (a = 0; a < 2; a++) {
            fresh2();
            g_car.TheControlMode = kMode[m];
            g_tctl.Acceleration = kAcc[a];
            g_tctl.TimeBeforeUpdate = 77.0f;
            g_tctl.PrevSpeed = 88.0f;
            // Every mode has a controller that would answer, so a read in
            // the wrong mode shows as a number rather than as nothing.
            g_car.pCarController = (CarController *)&g_tctl;
            printf("  mode %d acc %.9g -> %08x\n", (int)kMode[m],
                   (double)kAcc[a], wbits(car_get_tracked_acceleration(&g_car)));
        }
    }

    // And no controller at all outside REAL_CONTROL: the answer must come
    // without the read, or the harness crashes.
    for (m = 0; m < 7; m++) {
        if (kMode[m] == 1)
            continue;
        fresh2();
        g_car.TheControlMode = kMode[m];
        g_car.pCarController = NULL;
        printf("  mode %d no controller -> %08x\n", (int)kMode[m],
               wbits(car_get_tracked_acceleration(&g_car)));
    }
}

// ===================================================================== slice 3

// ComputeFakeRPM's tweakables, RPMTable and the yaw profile's points are
// all writable globals, and four scenarios below poke one of them to make a
// branch visible. Each poke is undone before the next fixture, from a copy
// taken once the static initialiser has run.

static float *const kTweak[11] = {
    &GearRTo1Speed, &Gear1To2Speed, &Gear2To3Speed, &Gear3To4Speed,
    &Gear4To5Speed, &Gear5To6Speed, &GearTopSpeed, &MaxRPMInc,
    &MaxSpeedInc, &TestSpeed, &TestRPM,
};
static const char *const kTweakName[11] = {
    "GearRTo1Speed", "Gear1To2Speed", "Gear2To3Speed", "Gear3To4Speed",
    "Gear4To5Speed", "Gear5To6Speed", "GearTopSpeed", "MaxRPMInc",
    "MaxSpeedInc", "TestSpeed", "TestRPM",
};

static float    s_tweak[11];
static float    s_rpm[12];
static bVector2 s_pcy[4];

static void save_tweaks(void)
{
    int i;

    for (i = 0; i < 11; i++)
        s_tweak[i] = *kTweak[i];
    memcpy(s_rpm, RPMTable, sizeof s_rpm);
    memcpy(s_pcy, PostCollisionYawControlProfileData, sizeof s_pcy);
}

static void restore_tweaks(void)
{
    int i;

    for (i = 0; i < 11; i++)
        *kTweak[i] = s_tweak[i];
    memcpy(RPMTable, s_rpm, sizeof s_rpm);
    memcpy(PostCollisionYawControlProfileData, s_pcy, sizeof s_pcy);
}

static void scenario_tweakables(void)
{
    int i;

    printf("[fake rpm tweakables]\n");
    for (i = 0; i < 11; i++)
        printf("  %-14s %08x\n", kTweakName[i], wbits(*kTweak[i]));
    for (i = 0; i < 12; i++)
        printf("  RPMTable[%d] %08x\n", i, wbits(RPMTable[i]));
}

// ------------------------------------------------ where the other cars are

// Every `other` carries a GeometryPosition and a Velocity nothing should
// read, so a method that takes the wrong field shows as a different answer.
static void set_other(Car *k, float px, float py)
{
    memset(k, 0, sizeof *k);
    k->State.Position.x = px;
    k->State.Position.y = py;
    k->State.Position.z = 3.0f;
    k->State.GeometryPosition.x = 777.0f;
    k->State.GeometryPosition.y = -777.0f;
    k->State.Velocity.x = 55.0f;
    k->State.Velocity.y = -66.0f;
    k->State.Angle = 12345;
}

static const float kOx[11] = {
    10.0f, 11.0f, 10.0f, 9.0f, 10.0f, 0.0f, -3.0f, 1.0f, 100.0f, 12.5f,
    -40.0f
};
static const float kOy[11] = {
    -5.0f, -5.0f, -4.0f, -5.0f, -6.0f, 0.0f, 7.0f, 2.0f, 100.0f, -7.25f,
    3.5f
};

static void scenario_left_right(void)
{
    static const int   kAng[5] = { 0, 16384, 8192, 0, 49152 };
    static const float kVx[5]  = { 0.0f, 0.0f, 0.0f, 3.0f, -2.0f };
    static const float kVy[5]  = { 0.0f, 0.0f, 0.0f, 4.0f, 0.5f };
    static const float kFs[5]  = { 1.0f, 1.0f, 1.0f, 5.0f, -1.0f };
    static const float kPx[5]  = { 10.0f, 0.0f, -3.0f, 1.0f, 100.0f };
    static const float kPy[5]  = { -5.0f, 0.0f, 7.0f, 2.0f, 100.0f };
    int i, j;

    printf("[left right]\n");
    for (i = 0; i < 5; i++) {
        for (j = 0; j < 11; j++) {
            int l, r;

            fresh();
            g_car.State.Angle = (uint16_t)kAng[i];
            g_car.State.Velocity.x = kVx[i];
            g_car.State.Velocity.y = kVy[i];
            g_car.State.ForwardSpeed = kFs[i];
            g_car.State.Position.x = kPx[i];
            g_car.State.Position.y = kPy[i];
            set_other(&g_others[0], kOx[j], kOy[j]);
            l = car_is_car_to_left(&g_car, &g_others[0]);
            g_car.State.MatrixValid = 0;
            r = car_is_car_to_right(&g_car, &g_others[0]);
            printf("  car %d other %-2d -> left %d right %d\n", i, j, l, r);
        }
    }
}

static void scenario_relative(void)
{
    static const float kPx[4] = { 0.0f, 5.0f, 0.0f, -20.0f };
    static const float kPy[4] = { 0.0f, -3.0f, 0.0f, 40.0f };
    static const float kVx[4] = { 1.0f, 3.0f, 0.0f, -0.6f };
    static const float kVy[4] = { 0.0f, 4.0f, 0.0f, 2.2f };
    static const float kQx[12] = {
        0.0f, 100.0f, 100.00001f, -100.0f, -100.00001f, 0.0f, 0.0f,
        50.0f, 99.9f, 65.0f, -30.0f, 5.0f
    };
    static const float kQy[12] = {
        0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 100.0f, -100.00001f,
        50.0f, -99.9f, 77.0f, 10.0f, -3.0f
    };
    int i, j;

    printf("[relative position]\n");
    for (i = 0; i < 4; i++) {
        for (j = 0; j < 12; j++) {
            float lat = -12345.0f, a1, a2;

            fresh();
            g_car.State.Position.x = kPx[i];
            g_car.State.Position.y = kPy[i];
            g_car.State.Velocity.x = kVx[i];
            g_car.State.Velocity.y = kVy[i];
            g_car.State.Velocity.z = 9.0f;
            set_other(&g_others[0], kQx[j], kQy[j]);
            a1 = car_get_relative_car_position(&g_car, &g_others[0], &lat);
            a2 = car_get_relative_car_position(&g_car, &g_others[0], NULL);
            printf("  car %d other %-2d -> along %08x lateral %08x "
                   "null %08x\n", i, j, wbits(a1), wbits(lat), wbits(a2));
        }
    }
}

static void scenario_in_front(void)
{
    static const int kAng[5] = { 0, 1000, 16384, 65000, 32768 };
    static const float kQx[8] = {
        10.0f, 0.0f, -10.0f, 0.0f, 10.0f, -7.0f, 0.0f, 3.5f
    };
    static const float kQy[8] = {
        0.0f, 10.0f, 0.0f, -10.0f, 10.0f, -3.0f, 0.0f, 0.25f
    };
    static const uint16_t kWithin[9] = {
        0, 1, 1000, 16384, 16385, 32767, 32768, 32769, 65535
    };
    int i, j, k;

    printf("[in front]\n");
    for (i = 0; i < 5; i++) {
        for (j = 0; j < 8; j++) {
            char r[10];

            for (k = 0; k < 9; k++) {
                fresh();
                g_car.State.Angle = (uint16_t)kAng[i];
                g_car.State.Position.x = 0.0f;
                g_car.State.Position.y = 0.0f;
                g_car.State.GeometryPosition.x = -555.0f;
                g_car.State.GeometryPosition.y = 444.0f;
                set_other(&g_others[0], kQx[j], kQy[j]);
                r[k] = (char)('0' + car_is_car_in_front(&g_car, &g_others[0],
                                                        kWithin[k]));
            }
            r[9] = 0;
            printf("  ang %-5d other %d -> %s\n", kAng[i], j, r);
        }
    }

    // And off the origin, one car with the others behind it and one with
    // them ahead, so a delta taken the wrong way round shows.
    printf("[in front moved]\n");
    for (i = 0; i < 2; i++) {
        for (j = 0; j < 8; j++) {
            fresh();
            g_car.State.Angle = 0;
            g_car.State.Position.x = i ? -20.0f : 20.0f;
            g_car.State.Position.y = i ? 4.0f : -4.0f;
            set_other(&g_others[0], kQx[j], kQy[j]);
            printf("  car %d other %d -> %d %d\n", i, j,
                   car_is_car_in_front(&g_car, &g_others[0], 8192),
                   car_is_car_in_front(&g_car, &g_others[0], 32768));
        }
    }
}

// ------------------------------------------------------ the car's own yaw

static void scenario_yaw_boost(void)
{
    static const uint32_t kStamp[16] = {
        0u, 0x7fffffffu, 1000u, 1000u, 1000u, 1000u, 1000u, 1000u,
        1000u, 1000u, 1000u, 5u, 0x80000000u, 0xfffffff0u, 0x7ffffffeu, 1u
    };
    static const uint32_t kNow[16] = {
        2000u, 0x800007cfu, 1000u, 1400u, 2600u, 3000u, 7000u, 9000u,
        16999u, 17000u, 500u, 0x7fffffffu, 0x7fffffffu, 0x00000010u,
        0x800007cdu, 2001u
    };
    int i, pass;

    for (pass = 0; pass < 2; pass++) {
        printf(pass ? "[yaw boost wide profile]\n" : "[yaw boost]\n");
        for (i = 0; i < 16; i++) {
            fresh2();
            // The Graph aliases the array, so a poke is seen through it
            // without running graph_init again. A last knee at 8 s makes
            // the four-second cutoff visible, and a first value that is
            // not 0 makes a negative elapsed time visible.
            if (pass) {
                PostCollisionYawControlProfileData[0].y = 0.125f;
                PostCollisionYawControlProfileData[3].x = 8.0f;
                PostCollisionYawControlProfileData[3].y = 0.5f;
            }
            g_body.LastPenetrationTime.PackedTime = 1u;
            g_body.LastYawControlCollisionTime.PackedTime = kStamp[i];
            WorldTimer = (int32_t)kNow[i];
            printf("  stamp %08x now %08x -> %08x\n", (unsigned)kStamp[i],
                   (unsigned)kNow[i],
                   wbits(car_get_post_collision_yaw_control_boost(&g_car)));
            restore_tweaks();
        }
    }
    WorldTimer = 0;
}

static void scenario_drifting(void)
{
    static const int   kWheels[3] = { 1, 2, 4 };
    // 1356 BAM is the first yaw past 0.13 one way; the other way it is
    // 1357 (64179), because the fold's `sub.s` of 2 pi rounds 64180 to
    // -0.12999964.
    static const int   kAng[5] = { 1355, 1356, 64179, 64180, 16384 };
    static const float kFs[4] = { 12.0f, 12.000001f, 30.0f, 4.9f };
    int w, a, f;

    printf("[drifting]\n");
    for (w = 0; w < 3; w++) {
        for (a = 0; a < 5; a++) {
            char r[5];

            for (f = 0; f < 4; f++) {
                fresh();
                g_car.State.nWheelsTouchingGround = kWheels[w];
                g_car.State.Angle = (uint16_t)kAng[a];
                g_car.State.Velocity.x = 20.0f;
                g_car.State.Velocity.y = 0.0f;
                g_car.State.ForwardSpeed = kFs[f];
                g_car.State.VelocityMagnitude = 1.0f;
                r[f] = (char)('0' + car_is_drifting(&g_car));
            }
            r[4] = 0;
            printf("  wheels %d ang %-5d -> %s\n", kWheels[w], kAng[a], r);
        }
    }
}

// --------------------------------------------------------- the fake engine

static void scenario_smooth(void)
{
    static const float kC[12] = {
        0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 10.0f, -0.0f, 0.0f, 0.0f, 5.0f,
        -3.25f, 1000.0f
    };
    static const float kT[12] = {
        5.0f, 1.0f, 0.5f, -1.0f, -5.0f, 10.0f, -0.0f, -0.0f, 0.5f, 7.0f,
        -3.3f, 8500.0f
    };
    static const float kR[12] = {
        1.0f, 1.0f, 1.0f, 1.0f, 1.0f, 0.0f, 0.0f, 0.0f, -1.0f, 1.5f,
        0.01f, 50.0f
    };
    int i;

    printf("[smooth]\n");
    for (i = 0; i < 12; i++)
        printf("  %.9g %.9g %.9g -> %08x\n", (double)kC[i], (double)kT[i],
               (double)kR[i], wbits(car_smooth(kC[i], kT[i], kR[i])));
}

static void rpm_line(const char *tag)
{
    printf("  %-10s old %08x gear %d rpm %08x\n", tag, wbits(g_car.OldSpeed),
           (int)g_car.State.CurrentGear, wbits(g_car.State.RPM));
}

// Two calls on one car: the first changes the gear from NEUTRAL, so its
// RPM is not smoothed; the second finds the gear it left and smooths.
static void rpm_twice(float vm, float old)
{
    fresh();
    g_car.State.VelocityMagnitude = vm;
    g_car.OldSpeed = old;
    g_car.State.CurrentGear = 1;
    g_car.State.RPM = 1000.0f;
    printf("  vm %.9g old %.9g\n", (double)vm, (double)old);
    car_compute_fake_rpm(&g_car);
    rpm_line("first");
    car_compute_fake_rpm(&g_car);
    rpm_line("second");
}

static void scenario_fake_rpm(void)
{
    static const float kSpeed[25] = {
        -30.0f, -25.38f, -5.0f, -2.00000024f, -2.0f, -1.0f, -0.0f, 0.0f, 10.0f, 25.3799973f,
        25.38f, 30.0f, 40.89f, 50.0f, 56.47f, 60.0f, 72.06f, 75.0f,
        79.9999924f, 80.0f, 85.0f, 89.5f, 89.5099945f, 89.51f, 100.0f
    };
    static const float kVm[5]  = { 50.0f, 10.0f, 30.0f, 89.0f, 120.0f };
    static const float kOld[5] = { 20.0f, 30.0f, 29.5f, 95.0f, 60.0f };
    int i;

    printf("[fake rpm bands]\n");
    for (i = 0; i < 25; i++)
        rpm_twice(kSpeed[i], kSpeed[i]);

    printf("[fake rpm smoothing]\n");
    for (i = 0; i < 5; i++)
        rpm_twice(kVm[i], kOld[i]);

    // TestSpeed replaces the speed only when above 0.
    printf("[fake rpm test speed]\n");
    TestSpeed = 45.0f;
    rpm_twice(10.0f, 45.0f);
    TestSpeed = -1.0f;
    rpm_twice(10.0f, 10.0f);
    restore_tweaks();

    // TestRPM is stored whenever it is not 100, and 0 is not 100.
    printf("[fake rpm test rpm]\n");
    TestRPM = 3000.0f;
    rpm_twice(30.0f, 30.0f);
    TestRPM = 0.0f;
    rpm_twice(60.0f, 60.0f);
    TestRPM = 100.0f;
    rpm_twice(60.0f, 60.0f);
    restore_tweaks();

    // The last band reads the eight bytes after RPMTable.
    printf("[fake rpm overread]\n");
    PostCollisionYawControlProfileData[0].x = 7000.0f;
    PostCollisionYawControlProfileData[0].y = 7500.0f;
    rpm_twice(85.0f, 85.0f);
    restore_tweaks();

    // Pair 1 is never read: the first band above Gear1To2Speed uses pair 2.
    printf("[fake rpm pair one]\n");
    RPMTable[2] = 1.0f;
    RPMTable[3] = 2.0f;
    rpm_twice(30.0f, 30.0f);
    rpm_twice(10.0f, 10.0f);
    restore_tweaks();

    // Pair 0 is what the bottom band reads, both ends.
    printf("[fake rpm pair zero]\n");
    RPMTable[0] = 1500.0f;
    RPMTable[1] = 4500.0f;
    rpm_twice(10.0f, 10.0f);
    restore_tweaks();
}

int main(int argc, char **argv)
{
    if (argc > 1)
        return abort_mode(argv[1]);

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

    scenario_layout2();
    scenario_static_init();
    scenario_draft_from();
    scenario_draft_sum();
    scenario_vtable();
    install_fakes();
    scenario_think();
    scenario_drive();
    scenario_route();
    scenario_sound();
    scenario_collideable();
    scenario_wrong_way();
    scenario_headlights();
    scenario_bbox();
    scenario_penetration();
    scenario_tracked();

    save_tweaks();
    scenario_tweakables();
    scenario_left_right();
    scenario_relative();
    scenario_in_front();
    scenario_yaw_boost();
    scenario_drifting();
    scenario_smooth();
    scenario_fake_rpm();
    return 0;
}
