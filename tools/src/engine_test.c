/* engine_test -- drives table.c and engine.c and prints a transcript that
   tools/engine_check.py reproduces from a model of the disassembly.

   Every float is printed %.9g so a one-ulp disagreement shows up as a
   diff rather than hiding behind a rounded decimal. */

#include <stdio.h>
#include <string.h>

#include "engine.h"
#include "table.h"
#include "carstate.h"

static int g_dirt;

static float dirt(void)
{
    g_dirt++;
    return -1000.0f - (float)g_dirt;
}

static int32_t dirti(void)
{
    g_dirt++;
    return -900 - g_dirt;
}

/* ------------------------------------------------------------------ Table */

static void scenario_table(void)
{
    /* Nine entries so the shape matches the torque curve the engine
       builds, plus a three-entry table for the braking curve's shape. */
    static const float nine[9] = { 10.0f, 20.0f, 45.0f, 80.0f, 120.0f,
                                   150.0f, 160.0f, 140.0f, 90.0f };
    static const float three[3] = { -5.0f, -12.5f, -30.0f };
    static const float one[1]   = { 7.25f };

    static const float args[] = {
        -100.0f, 0.0f, 800.0f, 1000.0f, 1000.5f, 2000.0f, 3125.0f,
        4000.0f, 5500.0f, 6999.0f, 7000.0f, 7000.5f, 9000.0f
    };

    Table t;
    size_t i;

    printf("== table ==\n");

    table_init(&t, nine, 9, 1000.0f, 7000.0f);
    printf("  nine  n %d min %.9g max %.9g mult %.9g\n",
           (int)t.NumEntries, t.MinArg, t.MaxArg, t.IndexMultiplier);
    for (i = 0; i < sizeof args / sizeof args[0]; i++)
        printf("    arg %-10.9g -> %.9g\n", args[i],
               table_get_value(&t, args[i]));

    table_init(&t, three, 3, 1000.0f, 7000.0f);
    printf("  three n %d min %.9g max %.9g mult %.9g\n",
           (int)t.NumEntries, t.MinArg, t.MaxArg, t.IndexMultiplier);
    for (i = 0; i < sizeof args / sizeof args[0]; i++)
        printf("    arg %-10.9g -> %.9g\n", args[i],
               table_get_value(&t, args[i]));

    /* A single-entry table: NumEntries-1 is 0, so the multiplier is 0 and
       every argument lands on index 0, which is also the last index. */
    table_init(&t, one, 1, 1000.0f, 7000.0f);
    printf("  one   n %d min %.9g max %.9g mult %.9g\n",
           (int)t.NumEntries, t.MinArg, t.MaxArg, t.IndexMultiplier);
    for (i = 0; i < sizeof args / sizeof args[0]; i++)
        printf("    arg %-10.9g -> %.9g\n", args[i],
               table_get_value(&t, args[i]));

    /* An inverted range. IndexMultiplier comes out negative, and the two
       clamps stop being interchangeable: the low test fires first and the
       high one is never reached, so an argument above MinArg is NOT pulled
       down to MaxArg. Nothing in the car data does this, but the listing
       commits to the order and so does the port. */
    table_init(&t, nine, 9, 7000.0f, 1000.0f);
    printf("  inverted n %d min %.9g max %.9g mult %.9g\n",
           (int)t.NumEntries, t.MinArg, t.MaxArg, t.IndexMultiplier);
    for (i = 0; i < sizeof args / sizeof args[0]; i++)
        printf("    arg %-10.9g -> %.9g\n", args[i],
               table_get_value(&t, args[i]));

    /* SetMinMax on a live table recomputes the multiplier. */
    table_init(&t, nine, 9, 1000.0f, 7000.0f);
    table_set_min_max(&t, 0.0f, 8.0f);
    printf("  rerange min %.9g max %.9g mult %.9g\n",
           t.MinArg, t.MaxArg, t.IndexMultiplier);
    for (i = 0; i < 10; i++)
        printf("    arg %-10.9g -> %.9g\n", (float)i * 0.75f,
               table_get_value(&t, (float)i * 0.75f));
}

/* ----------------------------------------------------------------- Engine */

static const EngineInfo g_ei = {
    /* IdleRPM         */ 1000.0f,
    /* RedLineRPM      */ 6500.0f,
    /* MaxRPM          */ 7000.0f,
    /* MomentOfInertia */ 0.25f,
    /* TorqueCurveTable */
    { 120.0f, 180.0f, 240.0f, 290.0f, 320.0f, 335.0f, 330.0f, 300.0f,
      250.0f },
    /* EngineBrakingTable */
    { 20.0f, 55.0f, 90.0f }
};

static void fill_pattern(Engine *e)
{
    g_dirt = 0;

    memset(e->_head, 0xA0, sizeof e->_head);
    e->_vtable   = 0xA0A0A0A0u;
    e->State.w   = dirt();
    e->EI        = 0;
    e->pCarState = 0;

    memset(&e->TorqueCurve,   0, sizeof e->TorqueCurve);
    memset(&e->EngineBraking, 0, sizeof e->EngineBraking);

    e->IsHP                    = dirti();
    e->Throttle                = dirt();
    e->RoadTorque              = dirt();
    e->ThrottleOverride        = dirt();
    e->NitroFlag               = dirti();
    e->NitroBoostTimer         = dirt();
    e->CatchupTorqueMultiplier = dirt();
}

static void print_engine(const char *tag, const Engine *e)
{
    printf("%s\n", tag);
    printf("  head       %02x%02x%02x%02x%02x%02x%02x%02x\n",
           e->_head[0], e->_head[1], e->_head[2], e->_head[3],
           e->_head[4], e->_head[5], e->_head[6], e->_head[7]);
    printf("  vtable     0x%08x\n", (unsigned)e->_vtable);
    printf("  w %.9g  rpm %.9g\n", e->State.w,
           e->State.w * ENGINE_RADS_TO_RPM);
    printf("  ei %s  cs %s\n", e->EI ? "set" : "null",
           e->pCarState ? "set" : "null");
    printf("  torquecurve   n %d min %.9g max %.9g mult %.9g\n",
           (int)e->TorqueCurve.NumEntries, e->TorqueCurve.MinArg,
           e->TorqueCurve.MaxArg, e->TorqueCurve.IndexMultiplier);
    printf("  enginebraking n %d min %.9g max %.9g mult %.9g\n",
           (int)e->EngineBraking.NumEntries, e->EngineBraking.MinArg,
           e->EngineBraking.MaxArg, e->EngineBraking.IndexMultiplier);
    printf("  ishp %d throttle %.9g roadtorque %.9g override %.9g\n",
           (int)e->IsHP, e->Throttle, e->RoadTorque, e->ThrottleOverride);
    printf("  nitro %d timer %.9g catchup %.9g\n",
           (int)e->NitroFlag, e->NitroBoostTimer,
           e->CatchupTorqueMultiplier);
}

static void scenario_ctor(void)
{
    Engine e;

    printf("== ctor ==\n");
    fill_pattern(&e);
    engine_init(&e, &g_ei, 0);
    print_engine("after ctor", &e);

    /* Throttle and RoadTorque are NOT initialised by the constructor. The
       two dirt values below are the ones fill_pattern put there, and their
       survival is the point of printing them. */
    printf("  uninitialised throttle %.9g roadtorque %.9g\n",
           e.Throttle, e.RoadTorque);
}

/* IdleRPM above MaxRPM. The two clamps in ComputeAuxiliaries are applied
   in a fixed order and the second overwrites the first, so which one wins
   is observable only when the range is inverted. */
static const EngineInfo g_ei_degenerate = {
    /* IdleRPM         */ 5000.0f,
    /* RedLineRPM      */ 6500.0f,
    /* MaxRPM          */ 2000.0f,
    /* MomentOfInertia */ 0.25f,
    { 120.0f, 180.0f, 240.0f, 290.0f, 320.0f, 335.0f, 330.0f, 300.0f,
      250.0f },
    { 20.0f, 55.0f, 90.0f }
};

static void scenario_auxiliaries(void)
{
    static const float w[] = {
        -50.0f, 0.0f, 10.0f, 104.719676f, 104.72f, 200.0f, 500.0f,
        732.0f, 733.037781f, 1000.0f
    };
    Engine e;
    size_t i;

    printf("== auxiliaries ==\n");
    for (i = 0; i < sizeof w / sizeof w[0]; i++) {
        fill_pattern(&e);
        engine_init(&e, &g_ei, 0);
        e.State.w     = w[i];
        e.RoadTorque  = 123.5f;
        engine_compute_auxiliaries(&e);
        printf("  w %-12.9g -> w %.9g rpm %.9g roadtorque %.9g\n",
               w[i], e.State.w, e.State.w * ENGINE_RADS_TO_RPM,
               e.RoadTorque);
    }

    for (i = 0; i < sizeof w / sizeof w[0]; i++) {
        fill_pattern(&e);
        engine_init(&e, &g_ei_degenerate, 0);
        e.State.w    = w[i];
        e.RoadTorque = 123.5f;
        engine_compute_auxiliaries(&e);
        printf("  degenerate w %-12.9g -> w %.9g rpm %.9g\n",
               w[i], e.State.w, e.State.w * ENGINE_RADS_TO_RPM);
    }
}

static void scenario_torque(void)
{
    static const float rpm[] = {
        500.0f, 1000.0f, 1750.0f, 2500.0f, 3250.0f, 4000.0f, 5000.0f,
        6000.0f, 6899.0f, 6900.0f, 6901.0f, 7000.0f, 8000.0f
    };
    static const float catchup[] = { 1.0f, 0.8f, 1.25f };
    static const int   ishp[]    = { 0, 1 };

    Engine e;
    size_t i, c, h;

    printf("== torque ==\n");
    for (h = 0; h < 2; h++) {
        for (c = 0; c < 3; c++) {
            printf("  ishp %d catchup %.9g\n", ishp[h], catchup[c]);
            for (i = 0; i < sizeof rpm / sizeof rpm[0]; i++) {
                fill_pattern(&e);
                engine_init(&e, &g_ei, 0);
                e.IsHP                    = ishp[h];
                e.CatchupTorqueMultiplier = catchup[c];
                e.State.w                 = rpm[i] * ENGINE_RPM_TO_RADS;

                printf("    rpm %-8.9g gettorque %-14.9g "
                       "getenginetorque %.9g\n",
                       rpm[i], engine_get_torque(&e),
                       engine_get_engine_torque(&e, rpm[i]));
            }
        }
    }
}

static void scenario_total(void)
{
    static const float rpm[]      = { 1000.0f, 2500.0f, 4000.0f, 6000.0f,
                                      6950.0f };
    static const float throttle[] = { 0.0f, 0.25f, 0.5f, 1.0f, 1.5f,
                                      -0.5f };
    static const int   nitro[]    = { 0, 1 };
    static const int   mode[]     = { 0, 1, 2 };

    CarState cs;
    Engine   e;
    size_t   i, t, n, m;

    printf("== total torque ==\n");
    memset(&cs, 0, sizeof cs);

    for (m = 0; m < 3; m++) {
        for (n = 0; n < 2; n++) {
            printf("  drivermode %d nitro %d\n", mode[m], nitro[n]);
            for (t = 0; t < sizeof throttle / sizeof throttle[0]; t++) {
                for (i = 0; i < sizeof rpm / sizeof rpm[0]; i++) {
                    fill_pattern(&e);
                    engine_init(&e, &g_ei, &cs);
                    cs.DriverMode = mode[m];
                    e.NitroFlag   = nitro[n];
                    e.Throttle    = throttle[t];
                    e.State.w     = rpm[i] * ENGINE_RPM_TO_RADS;
                    e.RoadTorque  = 0.0f;

                    printf("    rpm %-8.9g thr %-6.9g total %-14.9g "
                           "eff %-8.9g accel %.9g\n",
                           rpm[i], throttle[t],
                           engine_get_total_engine_torque(&e),
                           engine_get_effective_throttle(&e),
                           engine_get_angular_acceleration(&e));
                }
            }
        }
    }

    /* ThrottleOverride multiplies into the effective throttle, so it
       reaches both the drive term and the (1 - eff) braking term. */
    printf("  override sweep\n");
    for (t = 0; t < sizeof throttle / sizeof throttle[0]; t++) {
        fill_pattern(&e);
        engine_init(&e, &g_ei, &cs);
        cs.DriverMode       = 1;
        e.NitroFlag         = 0;
        e.Throttle          = 1.0f;
        e.ThrottleOverride  = throttle[t];
        e.State.w           = 3000.0f * ENGINE_RPM_TO_RADS;
        e.RoadTorque        = 0.0f;
        printf("    override %-6.9g total %-14.9g eff %.9g\n",
               throttle[t], engine_get_total_engine_torque(&e),
               engine_get_effective_throttle(&e));
    }
}

static void scenario_derivative(void)
{
    static const float road[] = { 0.0f, 50.0f, -50.0f, 1000.0f };
    CarState cs;
    Engine   e;
    size_t   i;
    float    out;
    int32_t  rc;

    printf("== derivative ==\n");
    memset(&cs, 0, sizeof cs);
    cs.DriverMode = 1;

    for (i = 0; i < sizeof road / sizeof road[0]; i++) {
        fill_pattern(&e);
        engine_init(&e, &g_ei, &cs);
        e.Throttle   = 0.75f;
        e.NitroFlag  = 0;
        e.State.w    = 3500.0f * ENGINE_RPM_TO_RADS;
        e.RoadTorque = 0.0f;

        engine_apply_torque(&e, road[i]);
        out = -12345.0f;
        rc  = engine_get_derivative(&e, &out);

        printf("  road %-10.9g roadtorque %-10.9g deriv %-14.9g rc %d "
               "accel %.9g response %.9g size %d\n",
               road[i], e.RoadTorque, out, (int)rc,
               engine_get_angular_acceleration(&e),
               engine_get_torque_response(&e), (int)engine_get_size(&e));
    }

    /* ApplyTorque accumulates; ComputeAuxiliaries is what clears it. */
    fill_pattern(&e);
    engine_init(&e, &g_ei, &cs);
    e.State.w    = 3000.0f * ENGINE_RPM_TO_RADS;
    e.RoadTorque = 0.0f;
    engine_apply_torque(&e, 10.0f);
    engine_apply_torque(&e, 2.5f);
    engine_apply_torque(&e, -1.25f);
    printf("  accumulated %.9g\n", e.RoadTorque);
    engine_compute_auxiliaries(&e);
    printf("  after auxiliaries %.9g\n", e.RoadTorque);
}

static void scenario_nitro(void)
{
    static const int32_t timers[] = { 0, 1000, 16000, 16001, 20000, 40000 };
    static const float   boost[]  = { 0.0f, 1.0f, 4.0f };
    Engine e;
    size_t i, b;

    printf("== nitro ==\n");
    for (b = 0; b < sizeof boost / sizeof boost[0]; b++) {
        for (i = 0; i < sizeof timers / sizeof timers[0]; i++) {
            fill_pattern(&e);
            engine_init(&e, &g_ei, 0);
            e.NitroFlag       = 1;
            e.NitroBoostTimer = boost[b];
            WorldTimer        = timers[i];
            engine_decrement_nitro(&e);
            printf("  boost %-6.9g timer %-7d worldsec %-12.9g flag %d\n",
                   boost[b], (int)timers[i],
                   (float)timers[i] * 0.000250000012f, (int)e.NitroFlag);
        }
    }

    /* A cleared flag is left alone whatever the clock says. */
    fill_pattern(&e);
    engine_init(&e, &g_ei, 0);
    e.NitroFlag       = 0;
    e.NitroBoostTimer = 0.0f;
    WorldTimer        = 1000000;
    engine_decrement_nitro(&e);
    printf("  already clear -> flag %d\n", (int)e.NitroFlag);
    WorldTimer = 0;
}

static void scenario_accessors(void)
{
    CarState cs;
    Engine   e;
    float    st;

    printf("== accessors ==\n");
    memset(&cs, 0, sizeof cs);

    fill_pattern(&e);
    engine_init(&e, &g_ei, &cs);

    engine_set_throttle(&e, 0.625f);
    engine_set_throttle_override(&e, 0.5f);
    engine_set_is_hp(&e, 1);
    engine_set_nitro_flag(&e, 1);
    engine_set_nitro_boost_timer(&e, 2.25f);
    engine_set_catchup_torque_multiplier(&e, 1.125f);
    engine_set_state(&e, 300.0f);

    printf("  w %.9g idle %.9g redline %.9g max %.9g\n",
           engine_get_angular_velocity(&e), engine_get_idle_rpm(&e),
           engine_get_red_line_rpm(&e), engine_get_max_rpm(&e));
    printf("  throttle %.9g eff %.9g ishp %d nitro %d timer %.9g\n",
           engine_get_throttle(&e), engine_get_effective_throttle(&e),
           (int)e.IsHP, (int)engine_get_nitro_flag(&e),
           engine_get_nitro_boost_timer(&e));
    printf("  ei %s state->w %.9g size %d\n",
           engine_get_ei(&e) == &g_ei ? "same" : "DIFFERENT",
           engine_get_state(&e)->w, (int)engine_get_size(&e));

    st = -1.0f;
    engine_get_state_f(&e, &st);
    printf("  getstate %.9g\n", st);

    st = 456.75f;
    engine_set_state_f(&e, &st);
    printf("  setstate %.9g\n", engine_get_angular_velocity(&e));

    engine_apply_torque(&e, 3.5f);
    printf("  applytorque %.9g response %.9g\n", e.RoadTorque,
           engine_get_torque_response(&e));
}

int main(void)
{
    printf("sizes engineps2 %d table %d engineinfo %d\n",
           (int)sizeof(EnginePS2), (int)sizeof(Table),
           (int)sizeof(EngineInfo));

    scenario_table();
    scenario_ctor();
    scenario_auxiliaries();
    scenario_torque();
    scenario_total();
    scenario_derivative();
    scenario_nitro();
    scenario_accessors();
    return 0;
}
