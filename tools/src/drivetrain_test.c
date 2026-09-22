// Transcript harness for DriveTrain.
// Cross-checked by tools/drivetrain_check.py, which models the same
// behaviour from the disassembly at 0x00182828..0x00183e10 without reading
// this file.
//
// Every fixture float is spelled as its own decimal literal rather than
// built by arithmetic -- 0.33f, not 0.32f + 0.01f -- because the model
// rounds each literal once and the C would round a sum twice. 0.32f +
// 0.01f is 0.329999983, one ulp below f32(0.33). Fixtures are not the
// thing under test, so they are written so that both sides cannot
// disagree about them.

#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "carstate.h"
#include "cartypeinfo.h"
#include "drivetrain.h"
#include "engine.h"
#include "wheel.h"

// ----------------------------------------------------------------- output

static void pf(const char *tag, float x)
{
    printf("%s %.9g\n", tag, (double)x);
}

static void pint(const char *tag, int x)
{
    printf("%s %d\n", tag, x);
}

static const char *gname(Gear g)
{
    switch ((int)g) {
    case -2: return "SPORT";
    case -1: return "AUTO";
    case  0: return "REV";
    case  1: return "NEU";
    case  2: return "1st";
    case  3: return "2nd";
    case  4: return "3rd";
    case  5: return "4th";
    case  6: return "5th";
    case  7: return "6th";
    case  8: return "7th";
    default: break;
    }

    {
        static char buf[4][16];
        static int which;
        char *p = buf[which++ & 3];
        sprintf(p, "g%d", (int)g);
        return p;
    }
}

static const char *cname(ClutchState c)
{
    static const char *names[4] = {
        "Disengaging", "Disengaged", "Engaging", "Engaged"
    };

    if (c >= 0 && c < 4)
        return names[c];

    {
        static char buf[2][16];
        static int which;
        char *p = buf[which++ & 1];
        sprintf(p, "c%d", (int)c);
        return p;
    }
}

// ----------------------------------------------------------- the fixtures

typedef struct Rig {
    DriveTrain     d;
    Engine         e;
    CarState       cs;
    Wheel          w[4];
    Wheel         *wp[4];
    WheelInfo      wi[4];
    DriveTrainInfo dti;
    EngineInfo     ei;
} Rig;

static const float kRadius[4] = { 0.32f, 0.33f, 0.34f, 0.35f };
static const float kMoment[4] = { 0.01f, 0.011f, 0.012f, 0.013f };
static const float kSpin[4]   = { 11.0f, 13.0f, 17.0f, 19.0f };

static void make_ei(EngineInfo *ei)
{
    static const float curve[9] = {
        110.0f, 168.0f, 213.0f, 246.0f, 268.0f, 275.0f, 250.0f, 195.0f, 130.0f
    };
    static const float braking[3] = { 0.0f, 28.0f, 62.0f };

    memset(ei, 0, sizeof *ei);
    ei->IdleRPM = 800.0f;
    ei->RedLineRPM = 6500.0f;
    ei->MaxRPM = 7000.0f;
    ei->MomentOfInertia = 0.25f;
    memcpy(ei->TorqueCurveTable, curve, sizeof curve);
    memcpy(ei->EngineBrakingTable, braking, sizeof braking);
}

static void make_dti(DriveTrainInfo *dti, float split, int32_t gears)
{
    static const float ratios[8] = {
        3.2f, 0.0f, 2.66f, 1.78f, 1.3f, 1.0f, 0.8f, 0.63f
    };

    memset(dti, 0, sizeof *dti);
    dti->ShiftUpPoint = 0.85f;
    dti->ShiftDownRPM = 0.5f;
    dti->FinalDrive[0] = 3.1f;
    dti->FinalDrive[1] = 3.55f;
    dti->TorqueSplit = split;
    dti->ClutchStiffness = 900.0f;
    dti->NumGears = gears;
    dti->ShiftSpeed = 2.5f;
    memcpy(dti->GearRatios, ratios, sizeof ratios);
}

static void rig_make(Rig *r, float split, int32_t gears, float throttle,
                     float ew, float speed, int32_t burnout, int32_t driver)
{
    int i;

    memset(r, 0, sizeof *r);

    make_ei(&r->ei);
    make_dti(&r->dti, split, gears);

    r->cs.VelocityMagnitude = speed;
    r->cs.BurnOutState = burnout;
    r->cs.DriverMode = driver;

    for (i = 0; i < 4; i++) {
        r->wi[i].Radius = kRadius[i];
        r->w[i].WI = &r->wi[i];
        r->w[i].MomentOfInertia = kMoment[i];
        r->wp[i] = &r->w[i];
    }

    engine_init(&r->e, &r->ei, &r->cs);
    r->e.Throttle = throttle;
    r->e.RoadTorque = 0.0f;
    r->e.State.w = ew;

    drivetrain_init(&r->d, &r->dti, &r->e, r->wp, &r->cs);
}

static void rig(Rig *r, float split)
{
    rig_make(r, split, 6, 0.0f, 0.0f, 0.0f, 0, 0);
}

static void spin_all(Rig *r)
{
    int i;

    for (i = 0; i < 4; i++)
        r->w[i].State.w = kSpin[i];
}

static void ground_all(Rig *r)
{
    int i;

    for (i = 0; i < 4; i++)
        r->w[i].TouchingGround = 1;
}

// --------------------------------------------------------------- printing

static void print_drivetrain(const char *tag, const DriveTrain *d)
{
    int i;
    char buf[64];

    sprintf(buf, "%s clutch", tag);
    pf(buf, d->State.clutch);

    printf("%s gears %s %s %s sport %s\n", tag, gname(d->DesiredGear),
           gname(d->CurrentGear), gname(d->PreviousGear),
           gname(d->SportGear));
    printf("%s clutchstate %s shifting %d\n", tag,
           cname(d->CurrentClutchState), (int)d->Shifting);

    sprintf(buf, "%s diffw", tag);
    pf(buf, d->DifferentialAngularVelocity);
    sprintf(buf, "%s hold", tag);
    pf(buf, d->GearHoldTime);

    for (i = 0; i < 9; i++)
        printf("%s up[%d] %.9g down[%d] %.9g\n", tag, i,
               (double)d->ShiftUpRPM[i], i, (double)d->ShiftDownRPM[i]);
}

static void print_wheels(const char *tag, const Wheel *w)
{
    int i;

    for (i = 0; i < 4; i++)
        printf("%s w%d spin %.9g torque %.9g slip %.9g/%.9g ground %d"
               " locked %d\n", tag, i, (double)w[i].State.w,
               (double)w[i].AppliedTorque, (double)w[i].CurrentSlip,
               (double)w[i].OldSlip, (int)w[i].TouchingGround,
               (int)w[i].BrakeLocked);
}

static void print_engine(const char *tag, const Engine *e)
{
    printf("%s engine w %.9g throttle %.9g road %.9g over %.9g\n", tag,
           (double)e->State.w, (double)e->Throttle, (double)e->RoadTorque,
           (double)e->ThrottleOverride);
}

static void dump_globals(const char *tag)
{
    char buf[64];

    sprintf(buf, "%s EngineBrakingFactor", tag);
    pf(buf, gEngineBrakingFactor);
    sprintf(buf, "%s ShiftUpDetune", tag);
    pf(buf, gShiftUpDetune);
    sprintf(buf, "%s ShiftDownDetune", tag);
    pf(buf, gShiftDownDetune);
    sprintf(buf, "%s GearShiftMethod", tag);
    pint(buf, (int)gGearShiftMethod);
    sprintf(buf, "%s LimitedSlip", tag);
    pf(buf, gLimitedSlip);
    sprintf(buf, "%s ClutchLimiter", tag);
    pf(buf, gClutchLimiter);
    sprintf(buf, "%s ClutchMatchedThreshold", tag);
    pf(buf, gClutchMatchedThreshold);
    sprintf(buf, "%s MaxDownShiftOver", tag);
    pf(buf, gMaxDownShiftOver);
    sprintf(buf, "%s WorldTimeElapsed", tag);
    pf(buf, WorldTimeElapsed);
}

// The eight tuning globals and the frame one, put back between scenarios
// the way the model's reset_globals() does.
static void reset_globals(void)
{
    gEngineBrakingFactor = 40.0f;
    gShiftUpDetune = 0.949999988f;
    gShiftDownDetune = 0.949999988f;
    gGearShiftMethod = 1;
    gLimitedSlip = 0.349999994f;
    gClutchLimiter = 300.0f;
    gClutchMatchedThreshold = 50.0f;
    gMaxDownShiftOver = 1.10000002f;
    WorldTimeElapsed = 0.0f;
}

// --------------------------------------------------------------- scenarios

static void s_layout(void)
{
    pint("sizeof DriveTrainState", (int)sizeof(DriveTrainState));
    pint("sizeof DriveTrain", (int)sizeof(DriveTrain));

    printf("off %-28s %d\n", "State", (int)offsetof(DriveTrain, State));
    printf("off %-28s %d\n", "DTI", (int)offsetof(DriveTrain, DTI));
    printf("off %-28s %d\n", "pEngine", (int)offsetof(DriveTrain, pEngine));
    printf("off %-28s %d\n", "pDriveWheel",
           (int)offsetof(DriveTrain, pDriveWheel));
    printf("off %-28s %d\n", "pCarState",
           (int)offsetof(DriveTrain, pCarState));
    printf("off %-28s %d\n", "DesiredGear",
           (int)offsetof(DriveTrain, DesiredGear));
    printf("off %-28s %d\n", "CurrentGear",
           (int)offsetof(DriveTrain, CurrentGear));
    printf("off %-28s %d\n", "PreviousGear",
           (int)offsetof(DriveTrain, PreviousGear));
    printf("off %-28s %d\n", "CurrentClutchState",
           (int)offsetof(DriveTrain, CurrentClutchState));
    printf("off %-28s %d\n", "Shifting",
           (int)offsetof(DriveTrain, Shifting));
    printf("off %-28s %d\n", "DifferentialAngularVelocity",
           (int)offsetof(DriveTrain, DifferentialAngularVelocity));
    printf("off %-28s %d\n", "GearHoldTime",
           (int)offsetof(DriveTrain, GearHoldTime));
    printf("off %-28s %d\n", "SportGear",
           (int)offsetof(DriveTrain, SportGear));
    printf("off %-28s %d\n", "ShiftUpRPM",
           (int)offsetof(DriveTrain, ShiftUpRPM));
    printf("off %-28s %d\n", "ShiftDownRPM",
           (int)offsetof(DriveTrain, ShiftDownRPM));

    printf("vtable 0x%08x\n", (unsigned)DRIVETRAIN_VTABLE);

    dump_globals("image");

    pf("ClutchSpeed[0]", DRIVETRAIN_CLUTCH_SPEED_DISENGAGING);
    pf("ClutchSpeed[1]", DRIVETRAIN_CLUTCH_SPEED_DISENGAGED);
    pf("ClutchSpeed[2]", DRIVETRAIN_CLUTCH_SPEED_ENGAGING);
    pf("ClutchSpeed[3]", DRIVETRAIN_CLUTCH_SPEED_ENGAGED);

    pf("rpm to rads", DRIVETRAIN_RPM_TO_RADS);
    pf("rads to rpm", DRIVETRAIN_RADS_TO_RPM);
    pf("rpm roundtrip", DRIVETRAIN_RPM_TO_RADS * DRIVETRAIN_RADS_TO_RPM);
}

static void shift_points_dump(const char *tag, const DriveTrainInfo *dti,
                              const EngineInfo *ei, float scale, int lo,
                              int hi)
{
    float up[9];
    float down[9];
    int i;

    for (i = 0; i < 9; i++) {
        up[i] = -1.0f;
        down[i] = -1.0f;
    }

    drivetrain_calculate_shift_points(dti, ei, up, down, scale);

    if (tag)
        printf("%s\n", tag);

    for (i = lo; i < hi; i++)
        printf("sp up[%d] %.9g down[%d] %.9g\n", i, (double)up[i], i,
               (double)down[i]);
}

static void s_shift_points(void)
{
    DriveTrainInfo dti;
    EngineInfo ei;
    EngineInfo alt;
    int gears;
    int i;

    reset_globals();
    make_ei(&ei);

    for (gears = 3; gears <= 6; gears += 3) {
        char tag[32];
        make_dti(&dti, 1.0f, gears);
        sprintf(tag, "sp gears %d", gears);
        shift_points_dump(tag, &dti, &ei, gShiftUpDetune, 0, 9);
    }

    make_dti(&dti, 1.0f, 6);
    shift_points_dump("sp scaled", &dti, &ei, 0.5f, 2, 8);

    // A flat torque curve never crosses over, so every gear takes the
    // MaxRPM - 200 fallback -- and the fallback is scaled.
    make_ei(&alt);
    for (i = 0; i < 9; i++)
        alt.TorqueCurveTable[i] = 200.0f;
    shift_points_dump("sp fallback", &dti, &alt, 0.5f, 2, 8);

    // (idle + max) / 2 is already past max - 200, so the search loop does
    // not run at all and `searching` is still the 1 the delay slot set.
    alt.IdleRPM = 6900.0f;
    alt.RedLineRPM = 6950.0f;
    shift_points_dump("sp noloop", &dti, &alt, 0.5f, 2, 8);

    // The same narrow band with a falling curve. Here a do/while would
    // find a crossover on its first probe and write 6950, where the entry
    // test writes the 6800 fallback: this is the fixture that tells the
    // two loop shapes apart.
    {
        static const float falling[9] = {
            300.0f, 260.0f, 220.0f, 170.0f, 100.0f, 80.0f, 70.0f, 65.0f,
            60.0f
        };
        memcpy(alt.TorqueCurveTable, falling, sizeof falling);
        shift_points_dump("sp noloop2", &dti, &alt, 0.5f, 2, 8);
    }

    // A curve that falls hard from idle, so every gear crosses over on
    // the search's first probe: that is what pins the loop's start at
    // (idle + MaxRPM) / 2 rather than (idle + RedLineRPM) / 2.
    {
        static const float steep[9] = {
            400.0f, 300.0f, 200.0f, 120.0f, 70.0f, 40.0f, 25.0f, 15.0f,
            10.0f
        };
        EngineInfo s;
        make_ei(&s);
        memcpy(s.TorqueCurveTable, steep, sizeof steep);
        shift_points_dump("sp steep", &dti, &s, 0.5f, 2, 8);
    }

    // A curve that is zero everywhere: `here` and `there` are both
    // exactly 0 at every probe, which is the only way to tell
    // `here < there` from `here <= there`.
    {
        EngineInfo z;
        int k;
        make_ei(&z);
        for (k = 0; k < 9; k++)
            z.TorqueCurveTable[k] = 0.0f;
        shift_points_dump("sp zerocurve", &dti, &z, 0.5f, 2, 8);
    }

    // The dead arm. gGearShiftMethod is 1 in the image.
    gGearShiftMethod = 0;
    shift_points_dump("sp interpolated", &dti, &ei, 0.5f, 2, 8);
    reset_globals();

    // NumGears 1 makes last 2, so the loop body never runs and only the
    // top-gear store happens.
    {
        DriveTrainInfo one;
        make_dti(&one, 1.0f, 1);
        shift_points_dump("sp onegear", &one, &ei, 0.5f, 0, 4);
    }
}

static void s_ctor(void)
{
    Rig r;
    int i;

    reset_globals();
    rig(&r, 1.0f);

    printf("ct vtable 0x%08x\n", (unsigned)r.d._vtable);
    print_drivetrain("ct", &r.d);
    printf("ct wired %d %d %d\n", r.d.DTI == &r.dti, r.d.pEngine == &r.e,
           r.d.pCarState == &r.cs);

    for (i = 0; i < 4; i++)
        printf("ct wheel%d %d\n", i, r.d.pDriveWheel[i] == &r.w[i]);

    // The four fields the constructor does not write, poisoned
    // first. A zeroed record cannot tell "left alone" from "set
    // to zero".
    {
        DriveTrain poisoned;

        memset(&poisoned, 0, sizeof poisoned);
        poisoned.PreviousGear = SEVENTH_GEAR;
        poisoned.DifferentialAngularVelocity = 12.5f;
        poisoned.GearHoldTime = 3.25f;
        poisoned.SportGear = FOURTH_GEAR;
        drivetrain_init(&poisoned, &r.dti, &r.e, r.wp, &r.cs);
        printf("ct keeps prev %s sport %s\n", gname(poisoned.PreviousGear),
               gname(poisoned.SportGear));
        printf("ct keeps diffw %.9g\n",
               (double)poisoned.DifferentialAngularVelocity);
        printf("ct keeps hold %.9g\n", (double)poisoned.GearHoldTime);
    }

    // The constructor hands gShiftUpDetune to CalculateShiftPoints
    // as the scale, and CalculateShiftPoints reaches for
    // gShiftDownDetune itself. The image ships both at 0.95, so only
    // a run with them apart says which global reaches which multiply.
    {
        Rig det;

        gShiftUpDetune = 0.8f;
        gShiftDownDetune = 0.6f;
        rig(&det, 1.0f);
        for (i = 0; i < 9; i++)
            printf("ct detune up[%d] %.9g down[%d] %.9g\n", i,
                   (double)det.d.ShiftUpRPM[i], i,
                   (double)det.d.ShiftDownRPM[i]);
        reset_globals();
    }
}

static void s_differential_velocity(void)
{
    static const char *tags[3] = { "rwd", "fwd", "awd" };
    static const float splits[3] = { 1.0f, 0.0f, 0.5f };
    static const Gear gears[5] = {
        REVERSE, NEUTRAL, FIRST_GEAR, FOURTH_GEAR, SIXTH_GEAR
    };
    static const float edges[4] = { 0.001f, 0.999f, 0.0009999f, 0.9991f };
    Rig r;
    int t;
    int g;
    char buf[64];

    reset_globals();

    for (t = 0; t < 3; t++) {
        rig(&r, splits[t]);
        spin_all(&r);

        for (g = 0; g < 5; g++) {
            r.d.CurrentGear = gears[g];
            sprintf(buf, "dv %s %s", tags[t], gname(gears[g]));
            pf(buf, drivetrain_get_differential_angular_velocity(&r.d));
        }

        printf("dv %s rwd %d fwd %d top %s\n", tags[t],
               (int)drivetrain_rear_wheel_drive(&r.d),
               (int)drivetrain_front_wheel_drive(&r.d),
               gname(drivetrain_get_top_gear(&r.d)));
    }

    for (t = 0; t < 4; t++) {
        rig(&r, edges[t]);
        spin_all(&r);
        r.d.CurrentGear = FIRST_GEAR;
        printf("dv edge %.9g rwd %d fwd %d value %.9g\n", (double)edges[t],
               (int)drivetrain_rear_wheel_drive(&r.d),
               (int)drivetrain_front_wheel_drive(&r.d),
               (double)drivetrain_get_differential_angular_velocity(&r.d));
    }
}

static void s_slippage(void)
{
    static const char *tags[3] = { "rwd", "fwd", "awd" };
    static const float splits[3] = { 1.0f, 0.0f, 0.5f };
    static const float slips[4] = { 0.25f, 0.75f, 1.25f, 1.75f };
    Rig r;
    int t;
    int i;
    char buf[32];

    reset_globals();

    for (t = 0; t < 3; t++) {
        rig(&r, splits[t]);
        for (i = 0; i < 4; i++)
            r.w[i].OldSlip = slips[i];
        sprintf(buf, "ds %s", tags[t]);
        pf(buf, drivetrain_get_drive_wheel_slippage(&r.d));
    }

    rig(&r, 0.0f);
    r.w[0].OldSlip = 1.0f;
    r.w[1].OldSlip = 1.0f;
    pf("ds fwd unit", drivetrain_get_drive_wheel_slippage(&r.d));
}

static void s_set_differential(void)
{
    static const char *tags[5] = {
        "rwd fast", "rwd slow", "fwd fast", "awd fast", "awd slow"
    };
    static const float splits[5] = { 1.0f, 1.0f, 0.0f, 0.5f, 0.5f };
    static const float speeds[5] = { 30.0f, 5.0f, 30.0f, 30.0f, 5.0f };
    Rig r;
    int t;
    int i;
    char buf[64];

    reset_globals();

    for (t = 0; t < 5; t++) {
        rig_make(&r, splits[t], 6, 0.0f, 0.0f, speeds[t], 0, 0);
        spin_all(&r);
        ground_all(&r);
        r.d.CurrentGear = THIRD_GEAR;

        sprintf(buf, "sv %s before", tags[t]);
        pf(buf, drivetrain_get_differential_angular_velocity(&r.d));

        drivetrain_set_differential_angular_velocity(&r.d, 120.0f);

        sprintf(buf, "sv %s", tags[t]);
        print_wheels(buf, r.w);

        sprintf(buf, "sv %s after", tags[t]);
        pf(buf, drivetrain_get_differential_angular_velocity(&r.d));
    }

    // The low-speed test is `<`, so the borderline speed is not slow. The
    // speed itself is derived the same way on both sides -- one float
    // divide of 40 by the mph factor -- so the two agree about it whether
    // or not it multiplies back to exactly 40.
    for (t = 0; t < 3; t++) {
        static const float nudge[3] = { 0.999f, 1.0f, 1.001f };
        float speed = (40.0f / 2.23699999f) * nudge[t];

        rig_make(&r, 1.0f, 6, 0.0f, 0.0f, speed, 0, 0);
        spin_all(&r);
        ground_all(&r);
        r.d.CurrentGear = THIRD_GEAR;
        drivetrain_set_differential_angular_velocity(&r.d, 120.0f);
        printf("sv mph%d %.9g w2 %.9g w3 %.9g\n", t,
               (double)(speed * 2.23699999f), (double)r.w[2].State.w,
               (double)r.w[3].State.w);
    }

    // Both rear wheels off the ground at speed averages them anyway; one
    // off does not.
    for (t = 0; t < 3; t++) {
        rig_make(&r, 1.0f, 6, 0.0f, 0.0f, 30.0f, 0, 0);
        spin_all(&r);
        ground_all(&r);
        for (i = 0; i < t; i++)
            r.w[2 + i].TouchingGround = 0;
        r.d.CurrentGear = THIRD_GEAR;
        drivetrain_set_differential_angular_velocity(&r.d, 120.0f);
        printf("sv lifted%d w2 %.9g w3 %.9g\n", t, (double)r.w[2].State.w,
               (double)r.w[3].State.w);
    }
}

static void s_differential_acceleration(void)
{
    static const char *tags[3] = { "rwd", "fwd", "awd" };
    static const float splits[3] = { 1.0f, 0.0f, 0.5f };
    static const float torques[4] = { 120.0f, 150.0f, 180.0f, 210.0f };
    static const float forces[4] = { 200.0f, 160.0f, 120.0f, 80.0f };
    static const Gear gears[4] = {
        REVERSE, NEUTRAL, FIRST_GEAR, SIXTH_GEAR
    };
    Rig r;
    int t;
    int i;
    char buf[32];

    reset_globals();

    for (t = 0; t < 3; t++) {
        rig(&r, splits[t]);
        for (i = 0; i < 4; i++) {
            r.w[i].AppliedTorque = torques[i];
            r.w[i].GroundForce[0] = forces[i];
        }
        r.d.CurrentGear = THIRD_GEAR;
        sprintf(buf, "da %s", tags[t]);
        pf(buf, drivetrain_get_differential_angular_acceleration(&r.d));
    }

    rig(&r, 0.5f);
    for (i = 0; i < 4; i++) {
        r.w[i].AppliedTorque = torques[i];
        r.w[i].GroundForce[0] = forces[i];
    }
    for (t = 0; t < 4; t++) {
        r.d.CurrentGear = gears[t];
        sprintf(buf, "da awd %s", gname(gears[t]));
        pf(buf, drivetrain_get_differential_angular_acceleration(&r.d));
    }
}

static void s_derivative(void)
{
    Rig r;
    float out[1];
    int state;
    char buf[32];

    reset_globals();
    rig(&r, 1.0f);

    out[0] = -1.0f;
    for (state = 0; state < 4; state++) {
        int ret;
        r.d.CurrentClutchState = (ClutchState)state;
        ret = drivetrain_get_derivative(&r.d, out);
        printf("gd %s %.9g ret %d\n", cname((ClutchState)state),
               (double)out[0], (int)ret);
    }

    printf("gd size %d\n", (int)drivetrain_get_size(&r.d));

    r.dti.ShiftSpeed = 0.4f;
    for (state = 0; state < 4; state++) {
        r.d.CurrentClutchState = (ClutchState)state;
        drivetrain_get_derivative(&r.d, out);
        sprintf(buf, "gd slow %s", cname((ClutchState)state));
        pf(buf, out[0]);
    }
}

static void s_idling_matched(void)
{
    static const float throttles[5] = { 0.0f, 0.29f, 0.3f, 0.31f, 1.0f };
    static const float deltas[4] = { -1.0f, 0.0f, 1e-5f, 1.0f };
    static const float ws[7] = {
        49.0f, 50.0f, 51.0f, 100.0f, 149.0f, 150.0f, 151.0f
    };
    static const float tight[3] = { 94.0f, 95.0f, 96.0f };
    Rig r;
    float idle_rads;
    int t;
    int i;

    reset_globals();
    rig(&r, 1.0f);

    idle_rads = r.ei.IdleRPM * DRIVETRAIN_RPM_TO_RADS + 9.99999975e-05f;

    for (t = 0; t < 5; t++) {
        r.e.Throttle = throttles[t];
        for (i = 0; i < 4; i++) {
            r.d.DifferentialAngularVelocity = idle_rads + deltas[i];
            printf("id t %.9g d %.9g -> %d\n", (double)throttles[t],
                   (double)deltas[i], (int)drivetrain_idling(&r.d));
        }
    }

    r.d.DifferentialAngularVelocity = 100.0f;
    for (i = 0; i < 7; i++) {
        r.e.State.w = ws[i];
        printf("cm w %.9g -> %d\n", (double)ws[i],
               (int)drivetrain_clutch_matched(&r.d));
    }

    gClutchMatchedThreshold = 5.0f;
    for (i = 0; i < 3; i++) {
        r.e.State.w = tight[i];
        printf("cm tight w %.9g -> %d\n", (double)tight[i],
               (int)drivetrain_clutch_matched(&r.d));
    }
    reset_globals();
}

static void s_apply_clutch_torque(void)
{
    static const float shares[10] = {
        0.0f, 20.0f, 34.0f, 35.0f, 36.0f, 50.0f, 64.0f, 65.0f, 66.0f, 100.0f
    };
    static const float airs[5] = { 10.0f, 49.0f, 50.0f, 51.0f, 90.0f };
    Rig r;
    int i;
    int b;

    reset_globals();

    for (i = 0; i < 10; i++) {
        rig(&r, 1.0f);
        // The front pair is spun too even though this is a rear-drive
        // car: ApplyClutchTorque splits *both* pairs whatever TorqueSplit
        // says, so two stationary front rims would divide zero by zero.
        // That is the image's behaviour and not this scenario's subject.
        spin_all(&r);
        r.w[2].State.w = shares[i];
        r.w[3].State.w = 100.0f - shares[i];
        ground_all(&r);
        r.d.CurrentGear = THIRD_GEAR;
        drivetrain_apply_clutch_torque(&r.d, 400.0f);
        printf("ac share %.9g w2 %.9g w3 %.9g road %.9g\n",
               (double)shares[i], (double)r.w[2].AppliedTorque,
               (double)r.w[3].AppliedTorque, (double)r.e.RoadTorque);
    }

    // Airborne widens the threshold to 0.5, which leaves no open band at
    // all: every share is clamped one way or the other.
    for (i = 0; i < 5; i++) {
        rig(&r, 1.0f);
        spin_all(&r);
        r.w[2].State.w = airs[i];
        r.w[3].State.w = 100.0f - airs[i];
        r.w[2].TouchingGround = 1;
        r.d.CurrentGear = THIRD_GEAR;
        drivetrain_apply_clutch_torque(&r.d, 400.0f);
        printf("ac air %.9g w2 %.9g w3 %.9g\n", (double)airs[i],
               (double)r.w[2].AppliedTorque, (double)r.w[3].AppliedTorque);
    }

    // Burnout, all four wheels, both values. This is the diagonal.
    for (b = 0; b < 3; b++) {
        rig_make(&r, 0.5f, 6, 0.0f, 0.0f, 0.0f, b, 0);
        spin_all(&r);
        ground_all(&r);
        r.d.CurrentGear = THIRD_GEAR;
        drivetrain_apply_clutch_torque(&r.d, 400.0f);
        printf("ac burn%d %.9g %.9g %.9g %.9g\n", b,
               (double)r.w[0].AppliedTorque, (double)r.w[1].AppliedTorque,
               (double)r.w[2].AppliedTorque, (double)r.w[3].AppliedTorque);
    }

    for (i = 0; i < 4; i++) {
        rig(&r, 0.5f);
        spin_all(&r);
        ground_all(&r);
        r.w[i].BrakeLocked = 1;
        r.d.CurrentGear = THIRD_GEAR;
        drivetrain_apply_clutch_torque(&r.d, 400.0f);
        printf("ac locked%d %.9g %.9g %.9g %.9g\n", i,
               (double)r.w[0].AppliedTorque, (double)r.w[1].AppliedTorque,
               (double)r.w[2].AppliedTorque, (double)r.w[3].AppliedTorque);
    }

    // NEUTRAL returns before RoadTorque is touched.
    rig(&r, 0.5f);
    spin_all(&r);
    ground_all(&r);
    r.e.RoadTorque = 77.0f;
    r.d.CurrentGear = NEUTRAL;
    drivetrain_apply_clutch_torque(&r.d, 400.0f);
    printf("ac neutral road %.9g torques %.9g %.9g %.9g %.9g\n",
           (double)r.e.RoadTorque, (double)r.w[0].AppliedTorque,
           (double)r.w[1].AppliedTorque, (double)r.w[2].AppliedTorque,
           (double)r.w[3].AppliedTorque);

    gLimitedSlip = 0.2f;
    rig(&r, 1.0f);
    spin_all(&r);
    r.w[2].State.w = 10.0f;
    r.w[3].State.w = 90.0f;
    ground_all(&r);
    r.d.CurrentGear = THIRD_GEAR;
    drivetrain_apply_clutch_torque(&r.d, 400.0f);
    printf("ac tightslip w2 %.9g w3 %.9g\n", (double)r.w[2].AppliedTorque,
           (double)r.w[3].AppliedTorque);
    reset_globals();
}

static void s_guess_clutch_torque(void)
{
    static const float slips[7] = {
        -500.0f, -300.0f, -50.0f, 0.0f, 50.0f, 300.0f, 500.0f
    };
    static const float clutches[3] = { 0.0f, 0.5f, 1.0f };
    Rig r;
    int state;
    int i;

    reset_globals();

    for (state = 0; state < 4; state++) {
        for (i = 0; i < 7; i++) {
            rig_make(&r, 1.0f, 6, 0.6f, 0.0f, 0.0f, 0, 0);
            spin_all(&r);
            ground_all(&r);
            r.d.CurrentGear = THIRD_GEAR;
            r.d.CurrentClutchState = (ClutchState)state;
            r.d.State.clutch = 0.75f;
            r.d.DifferentialAngularVelocity = 200.0f;
            r.e.State.w = 200.0f + slips[i];
            drivetrain_guess_clutch_torque(&r.d);
            printf("gc %s slip %.9g road %.9g w2 %.9g\n",
                   cname((ClutchState)state), (double)slips[i],
                   (double)r.e.RoadTorque, (double)r.w[2].AppliedTorque);
        }
    }

    for (i = 0; i < 3; i++) {
        rig_make(&r, 1.0f, 6, 0.6f, 0.0f, 0.0f, 0, 0);
        spin_all(&r);
        ground_all(&r);
        r.d.CurrentGear = THIRD_GEAR;
        r.d.CurrentClutchState = CLUTCH_ENGAGING;
        r.d.State.clutch = clutches[i];
        r.d.DifferentialAngularVelocity = 200.0f;
        r.e.State.w = 280.0f;
        drivetrain_guess_clutch_torque(&r.d);
        printf("gc clutch %.9g road %.9g\n", (double)clutches[i],
               (double)r.e.RoadTorque);
    }

    // DISENGAGED returns before it can apply anything, and the way to see
    // that is a negative zero. ApplyClutchTorque(0) is not a no-op: every
    // wheel gets `AppliedTorque + 0 * share`, and -0 + 0 is +0 in IEEE
    // 754. Torques that start at -0 print "-0" if the arm returned and
    // "0" if it went through ApplyClutchTorque. Every other observable is
    // unchanged by a zero torque, which is why this arm had nothing
    // holding it.
    rig_make(&r, 1.0f, 6, 0.6f, 0.0f, 0.0f, 0, 0);
    spin_all(&r);
    ground_all(&r);
    for (i = 0; i < 4; i++)
        r.w[i].AppliedTorque = -0.0f;
    r.d.CurrentGear = THIRD_GEAR;
    r.d.CurrentClutchState = CLUTCH_DISENGAGED;
    r.d.State.clutch = 0.75f;
    r.d.DifferentialAngularVelocity = 200.0f;
    r.e.State.w = 500.0f;
    r.e.RoadTorque = -0.0f;
    drivetrain_guess_clutch_torque(&r.d);
    printf("gc disengaged road %.9g\n", (double)r.e.RoadTorque);
    print_wheels("gc disengaged", r.w);
}

static void s_modify_clutch_torque(void)
{
    static const char *tags[3] = { "rwd", "fwd", "awd" };
    static const float splits[3] = { 1.0f, 0.0f, 0.5f };
    static const ClutchState states[2] = { CLUTCH_ENGAGING, CLUTCH_ENGAGED };
    static const float torques[4] = { 120.0f, 150.0f, 180.0f, 210.0f };
    static const float forces[4] = { 200.0f, 160.0f, 120.0f, 80.0f };
    static const float odds[2] = { 0.001f, 0.5f };
    Rig r;
    int t;
    int s;
    int i;

    reset_globals();

    for (t = 0; t < 3; t++) {
        for (s = 0; s < 2; s++) {
            rig_make(&r, splits[t], 6, 0.8f, 400.0f, 0.0f, 0, 0);
            spin_all(&r);
            ground_all(&r);
            for (i = 0; i < 4; i++) {
                r.w[i].AppliedTorque = torques[i];
                r.w[i].GroundForce[0] = forces[i];
            }
            r.d.CurrentGear = THIRD_GEAR;
            r.d.CurrentClutchState = states[s];
            r.e.RoadTorque = -60.0f;
            drivetrain_modify_clutch_torque(&r.d);
            printf("mc %s %s road %.9g torques %.9g %.9g %.9g %.9g\n",
                   tags[t], cname(states[s]), (double)r.e.RoadTorque,
                   (double)r.w[0].AppliedTorque,
                   (double)r.w[1].AppliedTorque,
                   (double)r.w[2].AppliedTorque,
                   (double)r.w[3].AppliedTorque);
        }
    }

    // Only pDriveWheel[0] and pDriveWheel[2] feed the inertia sum.
    for (t = 0; t < 2; t++) {
        rig_make(&r, 0.5f, 6, 0.8f, 400.0f, 0.0f, 0, 0);
        spin_all(&r);
        ground_all(&r);
        for (i = 0; i < 4; i++) {
            r.w[i].AppliedTorque = torques[i];
            r.w[i].GroundForce[0] = forces[i];
        }
        r.w[1].MomentOfInertia = odds[t];
        r.w[3].MomentOfInertia = odds[t];
        r.d.CurrentGear = THIRD_GEAR;
        r.d.CurrentClutchState = CLUTCH_ENGAGED;
        drivetrain_modify_clutch_torque(&r.d);
        printf("mc oddmoi %.9g road %.9g\n", (double)odds[t],
               (double)r.e.RoadTorque);
    }
}

static void s_compute_auxiliaries(void)
{
    static const float clutches[4] = { 1.0f, 0.5f, 0.0f, -0.25f };
    static const int32_t shifting[4] = { 0, 0, 0, 1 };
    static const float throttles[4] = { 0.0f, 0.3f, 0.31f, 0.0f };
    // The last entry is a clutch past 1. At exactly 1 the clamp writes
    // the value that is already there and cannot be seen.
    static const float engc[5] = { 0.5f, 1.0f, 1.0f, 1.0f, 1.5f };
    static const float engw[5] = {
        200.0f, 200.0f, 1000.0f, 1000.0f, 1000.0f
    };
    static const Gear enggear[5] = {
        THIRD_GEAR, THIRD_GEAR, THIRD_GEAR, NEUTRAL, THIRD_GEAR
    };
    Rig r;
    int i;

    reset_globals();

    // DISENGAGING: falls out until the clutch reaches zero.
    for (i = 0; i < 4; i++) {
        rig(&r, 1.0f);
        spin_all(&r);
        ground_all(&r);
        r.d.CurrentGear = THIRD_GEAR;
        r.d.CurrentClutchState = CLUTCH_DISENGAGING;
        r.d.State.clutch = clutches[i];
        drivetrain_compute_auxiliaries(&r.d);
        printf("ca out %.9g -> %s clutch %.9g over %.9g\n",
               (double)clutches[i], cname(r.d.CurrentClutchState),
               (double)r.d.State.clutch, (double)r.e.ThrottleOverride);
    }

    // DISENGAGED: the gear changes here.
    for (i = 0; i < 4; i++) {
        rig_make(&r, 1.0f, 6, throttles[i], 0.0f, 0.0f, 0, 0);
        spin_all(&r);
        ground_all(&r);
        r.d.CurrentGear = THIRD_GEAR;
        r.d.DesiredGear = FOURTH_GEAR;
        r.d.CurrentClutchState = CLUTCH_DISENGAGED;
        r.d.Shifting = shifting[i];
        drivetrain_compute_auxiliaries(&r.d);
        printf("ca in shift %d t %.9g -> %s gear %s shifting %d\n",
               (int)shifting[i], (double)throttles[i],
               cname(r.d.CurrentClutchState), gname(r.d.CurrentGear),
               (int)r.d.Shifting);
    }

    // ENGAGING: the clutch arrives, the match test and the neutral escape.
    for (i = 0; i < 5; i++) {
        rig_make(&r, 1.0f, 6, 0.6f, engw[i], 0.0f, 0, 0);
        spin_all(&r);
        ground_all(&r);
        r.d.CurrentGear = enggear[i];
        r.d.DesiredGear = enggear[i];
        r.d.CurrentClutchState = CLUTCH_ENGAGING;
        r.d.State.clutch = engc[i];
        drivetrain_compute_auxiliaries(&r.d);
        printf("ca engaging c %.9g w %.9g %s -> %s clutch %.9g over %.9g\n",
               (double)engc[i], (double)engw[i], gname(enggear[i]),
               cname(r.d.CurrentClutchState), (double)r.d.State.clutch,
               (double)r.e.ThrottleOverride);
    }

    // ENGAGING with the throttle shut and the wheels stopped, which is
    // what Idling asks for: the arm's last two instructions hand the
    // clutch straight back to DISENGAGING. Every other ENGAGING fixture
    // here is at 0.6 of throttle, where Idling is false before it ever
    // looks at the wheels.
    rig_make(&r, 1.0f, 6, 0.0f, 60.0f, 0.0f, 0, 0);
    r.d.CurrentGear = THIRD_GEAR;
    r.d.DesiredGear = THIRD_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGING;
    r.d.State.clutch = 0.5f;
    drivetrain_compute_auxiliaries(&r.d);
    printf("ca engaging idle -> %s clutch %.9g diffw %.9g idling %d\n",
           cname(r.d.CurrentClutchState), (double)r.d.State.clutch,
           (double)r.d.DifferentialAngularVelocity,
           (int)drivetrain_idling(&r.d));

    // ENGAGED, no wheelspin: the engine is dragged 4% towards the
    // drivetrain.
    rig_make(&r, 1.0f, 6, 0.6f, 300.0f, 0.0f, 0, 0);
    spin_all(&r);
    ground_all(&r);
    r.d.CurrentGear = THIRD_GEAR;
    r.d.DesiredGear = THIRD_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGED;
    r.d.State.clutch = 1.0f;
    drivetrain_compute_auxiliaries(&r.d);
    printf("ca engaged drag -> %s\n", cname(r.d.CurrentClutchState));
    print_engine("ca engaged drag", &r.e);
    pf("ca engaged drag diffw", r.d.DifferentialAngularVelocity);

    // ENGAGED with wheelspin: the whole drivetrain is snapped to the
    // engine instead.
    rig_make(&r, 1.0f, 6, 0.6f, 300.0f, 30.0f, 0, 0);
    spin_all(&r);
    ground_all(&r);
    for (i = 0; i < 4; i++)
        r.w[i].OldSlip = 0.5f;
    r.d.CurrentGear = THIRD_GEAR;
    r.d.DesiredGear = THIRD_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGED;
    r.d.State.clutch = 1.0f;
    drivetrain_compute_auxiliaries(&r.d);
    printf("ca engaged spin -> %s\n", cname(r.d.CurrentClutchState));
    print_engine("ca engaged spin", &r.e);
    pf("ca engaged spin diffw", r.d.DifferentialAngularVelocity);
    print_wheels("ca engaged spin", r.w);

    // ENGAGED in NEUTRAL: ThrottleOverride is still written, and nothing
    // else in the arm runs.
    //
    // The pedal starts at 0.25 rather than where the constructor left it.
    // Engine::Engine writes 1.0, which is exactly what this arm writes,
    // so against a fresh engine the store is invisible.
    //
    // The wheels and the cached differential speed are printed because
    // that is where "nothing else runs" shows.
    rig_make(&r, 1.0f, 6, 0.6f, 300.0f, 0.0f, 0, 0);
    spin_all(&r);
    ground_all(&r);
    for (i = 0; i < 4; i++)
        r.w[i].OldSlip = 0.5f;
    r.d.CurrentGear = NEUTRAL;
    r.d.DesiredGear = NEUTRAL;
    r.d.CurrentClutchState = CLUTCH_ENGAGED;
    r.e.ThrottleOverride = 0.25f;
    drivetrain_compute_auxiliaries(&r.d);
    print_engine("ca engaged neutral", &r.e);
    pf("ca engaged neutral diffw", r.d.DifferentialAngularVelocity);
    print_wheels("ca engaged neutral", r.w);
    printf("ca engaged neutral -> %s\n", cname(r.d.CurrentClutchState));

    // NEUTRAL with a shift pending. The gear test at the foot of the arm
    // sits outside the NEUTRAL guard, so this one disengages and sets
    // Shifting even though the physics above it was skipped.
    rig_make(&r, 1.0f, 6, 0.6f, 300.0f, 0.0f, 0, 0);
    spin_all(&r);
    ground_all(&r);
    for (i = 0; i < 4; i++)
        r.w[i].OldSlip = 0.5f;
    r.d.CurrentGear = NEUTRAL;
    r.d.DesiredGear = THIRD_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGED;
    r.e.ThrottleOverride = 0.25f;
    drivetrain_compute_auxiliaries(&r.d);
    print_engine("ca neutral shift", &r.e);
    pf("ca neutral shift diffw", r.d.DifferentialAngularVelocity);
    print_wheels("ca neutral shift", r.w);
    printf("ca neutral shift -> %s shifting %d\n",
           cname(r.d.CurrentClutchState), (int)r.d.Shifting);

    // ENGAGED with a shift pending.
    rig_make(&r, 1.0f, 6, 0.6f, 300.0f, 0.0f, 0, 0);
    spin_all(&r);
    ground_all(&r);
    r.d.CurrentGear = THIRD_GEAR;
    r.d.DesiredGear = FOURTH_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGED;
    drivetrain_compute_auxiliaries(&r.d);
    printf("ca engaged shift -> %s shifting %d\n",
           cname(r.d.CurrentClutchState), (int)r.d.Shifting);

    // A clutch state the enum does not have falls through untouched.
    rig(&r, 1.0f);
    spin_all(&r);
    r.d.CurrentGear = THIRD_GEAR;
    r.d.CurrentClutchState = (ClutchState)-1;
    r.e.ThrottleOverride = 0.125f;
    drivetrain_compute_auxiliaries(&r.d);
    printf("ca bogus -> %d over %.9g diffw %.9g\n",
           (int)r.d.CurrentClutchState, (double)r.e.ThrottleOverride,
           (double)r.d.DifferentialAngularVelocity);
}

static void s_sport_gear(void)
{
    Rig r;
    int g;

    reset_globals();
    rig(&r, 1.0f);

    for (g = -2; g <= 9; g++) {
        Gear got;
        if (g == 4 || g == 5)
            continue;
        r.d.SportGear = NEUTRAL;
        r.d.GearHoldTime = 3.5f;
        got = drivetrain_set_sport_gear(&r.d, (Gear)g);
        printf("sg ask %s -> %s hold %.9g\n", gname((Gear)g), gname(got),
               (double)r.d.GearHoldTime);
    }

    r.d.SportGear = THIRD_GEAR;
    r.d.GearHoldTime = 3.5f;
    {
        Gear got = drivetrain_set_sport_gear(&r.d, FOURTH_GEAR);
        printf("sg from3rd -> %s hold %.9g\n", gname(got),
               (double)r.d.GearHoldTime);
    }
}

static void s_automatic(void)
{
    static const Gear lows[2] = { REVERSE, NEUTRAL };
    static const char *uptags[5] = {
        "clean", "slip0", "slip3", "air1", "air2"
    };
    static const Gear downgear[3] = {
        FOURTH_GEAR, FOURTH_GEAR, THIRD_GEAR
    };
    static const float downw[3] = { 120.0f, 400.0f, 120.0f };
    static const Gear crawlgear[2] = { FIRST_GEAR, SECOND_GEAR };
    static const float crawlt[3] = { 0.1f, 0.2f, 0.9f };
    static const Gear directs[5] = {
        REVERSE, NEUTRAL, FIFTH_GEAR, SEVENTH_GEAR, (Gear)42
    };
    Rig r;
    int i;
    int j;

    reset_globals();

    for (i = 0; i < 2; i++) {
        Gear got;
        rig_make(&r, 1.0f, 6, 0.0f, 700.0f, 0.0f, 0, 0);
        r.d.CurrentGear = lows[i];
        // Fifth, not the first the constructor left there: the arm's
        // whole effect is the store of FIRST_GEAR, and against a record
        // that already holds it the store cannot be seen.
        r.d.DesiredGear = FIFTH_GEAR;
        r.d.CurrentClutchState = CLUTCH_ENGAGED;
        got = drivetrain_set_desired_gear(&r.d, AUTOMATIC);
        printf("au from %s -> %s desired %s sport %s\n", gname(lows[i]),
               gname(got), gname(r.d.DesiredGear), gname(r.d.SportGear));
    }

    // The wheels are on the ground and the engine is over third's up
    // point, so this is a frame that would upshift if the clutch test let
    // it through. Without that, the early return has nothing to prevent.
    rig_make(&r, 1.0f, 6, 0.9f, 700.0f, 0.0f, 0, 0);
    ground_all(&r);
    r.d.CurrentGear = THIRD_GEAR;
    r.d.DesiredGear = THIRD_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGING;
    drivetrain_set_desired_gear(&r.d, AUTOMATIC);
    printf("au notengaged desired %s sport %s (rpm %.9g up %.9g)\n",
           gname(r.d.DesiredGear), gname(r.d.SportGear),
           (double)(r.e.State.w * DRIVETRAIN_RADS_TO_RPM),
           (double)r.d.ShiftUpRPM[THIRD_GEAR]);

    for (i = 0; i < 5; i++) {
        rig_make(&r, 1.0f, 6, 0.9f, 700.0f, 0.0f, 0, 0);
        ground_all(&r);
        if (i == 1)
            r.w[0].CurrentSlip = 4.0f;
        else if (i == 2)
            r.w[3].CurrentSlip = 9.0f;
        else if (i == 3)
            r.w[1].TouchingGround = 0;
        else if (i == 4)
            r.w[2].TouchingGround = 0;
        r.d.CurrentGear = THIRD_GEAR;
        r.d.DesiredGear = THIRD_GEAR;
        r.d.CurrentClutchState = CLUTCH_ENGAGED;
        drivetrain_set_desired_gear(&r.d, AUTOMATIC);
        printf("au up %s desired %s (rpm %.9g over %.9g)\n", uptags[i],
               gname(r.d.DesiredGear),
               (double)(r.e.State.w * DRIVETRAIN_RADS_TO_RPM),
               (double)r.d.ShiftUpRPM[THIRD_GEAR]);
    }

    rig_make(&r, 1.0f, 6, 0.9f, 760.0f, 0.0f, 0, 0);
    ground_all(&r);
    r.d.CurrentGear = SIXTH_GEAR;
    r.d.DesiredGear = SIXTH_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGED;
    drivetrain_set_desired_gear(&r.d, AUTOMATIC);
    printf("au top desired %s\n", gname(r.d.DesiredGear));

    for (i = 0; i < 3; i++) {
        rig_make(&r, 1.0f, 6, 0.9f, downw[i], 0.0f, 0, 0);
        ground_all(&r);
        r.d.CurrentGear = downgear[i];
        r.d.DesiredGear = downgear[i];
        r.d.CurrentClutchState = CLUTCH_ENGAGED;
        drivetrain_set_desired_gear(&r.d, AUTOMATIC);
        printf("au down %s w %.9g desired %s (down %.9g rpm %.9g)\n",
               gname(downgear[i]), (double)downw[i],
               gname(r.d.DesiredGear),
               (double)r.d.ShiftDownRPM[downgear[i]],
               (double)(downw[i] * DRIVETRAIN_RADS_TO_RPM));
    }

    for (i = 0; i < 2; i++) {
        for (j = 0; j < 3; j++) {
            rig_make(&r, 1.0f, 6, crawlt[j], 70.0f, 0.0f, 0, 0);
            ground_all(&r);
            r.d.CurrentGear = crawlgear[i];
            r.d.DesiredGear = crawlgear[i];
            r.d.CurrentClutchState = CLUTCH_ENGAGED;
            drivetrain_set_desired_gear(&r.d, AUTOMATIC);
            printf("au crawl %s t %.9g desired %s\n", gname(crawlgear[i]),
                   (double)crawlt[j], gname(r.d.DesiredGear));
        }
    }

    // Both of the automatic's thresholds, sat on exactly. The point is
    // written back as the very rpm the object will compute, from the same
    // product on both sides, so the comparison is against itself.
    rig_make(&r, 1.0f, 6, 0.9f, 700.0f, 0.0f, 0, 0);
    ground_all(&r);
    r.d.CurrentGear = THIRD_GEAR;
    r.d.DesiredGear = THIRD_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGED;
    r.d.ShiftUpRPM[THIRD_GEAR] = r.e.State.w * DRIVETRAIN_RADS_TO_RPM;
    drivetrain_set_desired_gear(&r.d, AUTOMATIC);
    printf("au up-exact desired %s (rpm %.9g up %.9g)\n",
           gname(r.d.DesiredGear),
           (double)(r.e.State.w * DRIVETRAIN_RADS_TO_RPM),
           (double)r.d.ShiftUpRPM[THIRD_GEAR]);

    rig_make(&r, 1.0f, 6, 0.9f, 300.0f, 0.0f, 0, 0);
    ground_all(&r);
    r.d.CurrentGear = FOURTH_GEAR;
    r.d.DesiredGear = FOURTH_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGED;
    r.d.ShiftDownRPM[FOURTH_GEAR] = r.e.State.w * DRIVETRAIN_RADS_TO_RPM;
    drivetrain_set_desired_gear(&r.d, AUTOMATIC);
    printf("au down-exact desired %s (rpm %.9g down %.9g)\n",
           gname(r.d.DesiredGear),
           (double)(r.e.State.w * DRIVETRAIN_RADS_TO_RPM),
           (double)r.d.ShiftDownRPM[FOURTH_GEAR]);

    for (i = 0; i < 5; i++) {
        Gear got;
        rig(&r, 1.0f);
        got = drivetrain_set_desired_gear(&r.d, directs[i]);
        printf("au direct %s -> %s desired %s\n", gname(directs[i]),
               gname(got), gname(r.d.DesiredGear));
    }
}

static void s_sport_shift(void)
{
    static const float downws[2] = { 150.0f, 700.0f };
    static const float crawlt[2] = { 0.1f, 0.9f };
    static const float holds[3] = { 9.9f, 10.0f, 10.1f };
    // 720 is the one that matters: 6875.5 RPM is over MaxRPM - 300 and
    // under MaxRPM, so it is the only speed here that tells the margin
    // from no margin at all. 760 is over both and 400 is under both.
    static const Gear prevs[4] = {
        THIRD_GEAR, THIRD_GEAR, FIFTH_GEAR, THIRD_GEAR
    };
    static const float limw[4] = { 760.0f, 400.0f, 760.0f, 720.0f };
    static const float overs[2] = { 1.1f, 0.4f };
    Rig r;
    Gear got;
    int i;

    reset_globals();

    rig_make(&r, 1.0f, 6, 0.0f, 400.0f, 0.0f, 0, 0);
    r.d.CurrentGear = THIRD_GEAR;
    r.d.DesiredGear = THIRD_GEAR;
    r.d.SportGear = THIRD_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGING;
    for (i = 0; i < 3; i++)
        drivetrain_set_desired_gear(&r.d, SPORT_SHIFT);
    pf("ss hold image", r.d.GearHoldTime);

    WorldTimeElapsed = 1.0f / 60.0f;

    rig_make(&r, 1.0f, 6, 0.0f, 400.0f, 0.0f, 0, 0);
    r.d.CurrentGear = THIRD_GEAR;
    r.d.DesiredGear = FOURTH_GEAR;
    r.d.SportGear = THIRD_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGING;
    got = drivetrain_set_desired_gear(&r.d, SPORT_SHIFT);
    printf("ss notengaged -> %s desired %s hold %.9g\n", gname(got),
           gname(r.d.DesiredGear), (double)r.d.GearHoldTime);

    rig_make(&r, 1.0f, 6, 0.0f, 400.0f, 0.0f, 0, 0);
    r.d.CurrentGear = THIRD_GEAR;
    r.d.DesiredGear = THIRD_GEAR;
    r.d.SportGear = FOURTH_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGED;
    r.d.GearHoldTime = 2.0f;
    got = drivetrain_set_desired_gear(&r.d, SPORT_SHIFT);
    printf("ss up -> %s desired %s prev %s hold %.9g\n", gname(got),
           gname(r.d.DesiredGear), gname(r.d.PreviousGear),
           (double)r.d.GearHoldTime);

    for (i = 0; i < 2; i++) {
        rig_make(&r, 1.0f, 6, 0.0f, downws[i], 0.0f, 0, 0);
        r.d.CurrentGear = FOURTH_GEAR;
        r.d.DesiredGear = FOURTH_GEAR;
        r.d.SportGear = THIRD_GEAR;
        r.d.CurrentClutchState = CLUTCH_ENGAGED;
        r.d.GearHoldTime = 2.0f;
        got = drivetrain_set_desired_gear(&r.d, SPORT_SHIFT);
        printf("ss down w %.9g -> %s desired %s sport %s hold %.9g\n",
               (double)downws[i], gname(got), gname(r.d.DesiredGear),
               gname(r.d.SportGear), (double)r.d.GearHoldTime);
    }

    for (i = 0; i < 2; i++) {
        rig_make(&r, 1.0f, 6, crawlt[i], 70.0f, 0.0f, 0, 0);
        r.d.CurrentGear = SECOND_GEAR;
        r.d.DesiredGear = SECOND_GEAR;
        r.d.SportGear = FIRST_GEAR;
        r.d.CurrentClutchState = CLUTCH_ENGAGED;
        got = drivetrain_set_desired_gear(&r.d, SPORT_SHIFT);
        printf("ss crawl t %.9g -> %s desired %s sport %s\n",
               (double)crawlt[i], gname(got), gname(r.d.DesiredGear),
               gname(r.d.SportGear));
    }

    for (i = 0; i < 3; i++) {
        rig_make(&r, 1.0f, 6, 0.0f, 400.0f, 0.0f, 0, 0);
        r.d.CurrentGear = FOURTH_GEAR;
        r.d.DesiredGear = FOURTH_GEAR;
        r.d.SportGear = FOURTH_GEAR;
        r.d.PreviousGear = FOURTH_GEAR;
        r.d.CurrentClutchState = CLUTCH_ENGAGED;
        r.d.GearHoldTime = holds[i] - WorldTimeElapsed;
        got = drivetrain_set_desired_gear(&r.d, SPORT_SHIFT);
        printf("ss held %d -> %s\n", i, gname(got));
    }

    for (i = 0; i < 4; i++) {
        rig_make(&r, 1.0f, 6, 0.0f, limw[i], 0.0f, 0, 0);
        r.d.CurrentGear = FOURTH_GEAR;
        r.d.DesiredGear = FOURTH_GEAR;
        r.d.SportGear = FOURTH_GEAR;
        r.d.PreviousGear = prevs[i];
        r.d.CurrentClutchState = CLUTCH_ENGAGED;
        r.d.GearHoldTime = 0.0f;
        got = drivetrain_set_desired_gear(&r.d, SPORT_SHIFT);
        printf("ss limiter prev %s w %.9g -> %s (rpm %.9g max %.9g)\n",
               gname(prevs[i]), (double)limw[i], gname(got),
               (double)(limw[i] * DRIVETRAIN_RADS_TO_RPM),
               (double)(r.ei.MaxRPM - 300.0f));
    }

    // The refusal test sat on exactly. In second the down point is
    // IdleRPM + 100 = 900 whole, and 94.2477036 is the one float whose
    // product with the object's rads-to-RPM constant is exactly 900. So
    // `down < rpm` is false and `down <= rpm` is true: a refusal puts the
    // request back at second, letting it through drops to first.
    rig_make(&r, 1.0f, 6, 0.0f, 94.2477036f, 0.0f, 0, 0);
    r.d.CurrentGear = SECOND_GEAR;
    r.d.DesiredGear = SECOND_GEAR;
    r.d.SportGear = FIRST_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGED;
    r.d.GearHoldTime = 2.0f;
    got = drivetrain_set_desired_gear(&r.d, SPORT_SHIFT);
    printf("ss refuse-exact -> %s desired %s sport %s hold %.9g (rpm %.9g)\n",
           gname(got), gname(r.d.DesiredGear), gname(r.d.SportGear),
           (double)r.d.GearHoldTime,
           (double)(r.e.State.w * DRIVETRAIN_RADS_TO_RPM));

    for (i = 0; i < 2; i++) {
        gMaxDownShiftOver = overs[i];
        rig_make(&r, 1.0f, 6, 0.0f, 400.0f, 0.0f, 0, 0);
        r.d.CurrentGear = FOURTH_GEAR;
        r.d.DesiredGear = FOURTH_GEAR;
        r.d.SportGear = THIRD_GEAR;
        r.d.CurrentClutchState = CLUTCH_ENGAGED;
        drivetrain_set_desired_gear(&r.d, SPORT_SHIFT);
        printf("ss over %.9g desired %s sport %s\n", (double)overs[i],
               gname(r.d.DesiredGear), gname(r.d.SportGear));
    }

    reset_globals();
}

static void s_accessors(void)
{
    Rig r;
    float out[1];
    int state;
    int g;

    reset_globals();
    rig_make(&r, 0.5f, 5, 0.0f, 0.0f, 0.0f, 0, 0);

    r.d.DesiredGear = FOURTH_GEAR;
    r.d.CurrentGear = THIRD_GEAR;
    r.d.PreviousGear = SECOND_GEAR;
    r.d.SportGear = FIFTH_GEAR;

    printf("ax gears %s %s %s %s top %s\n",
           gname(drivetrain_get_desired_gear(&r.d)),
           gname(drivetrain_get_current_gear(&r.d)),
           gname(drivetrain_get_previous_gear(&r.d)),
           gname(drivetrain_get_sport_gear(&r.d)),
           gname(drivetrain_get_top_gear(&r.d)));
    printf("ax drive rwd %d fwd %d\n",
           (int)drivetrain_rear_wheel_drive(&r.d),
           (int)drivetrain_front_wheel_drive(&r.d));

    for (state = -1; state <= 4; state++) {
        r.d.CurrentClutchState = (ClutchState)state;
        printf("ax engaged %d -> %d\n", state,
               (int)drivetrain_is_clutch_engaged(&r.d));
    }

    for (g = 0; g < 9; g++)
        printf("ax rpm %s up %.9g down %.9g\n", gname((Gear)g),
               (double)drivetrain_get_shift_up_rpm(&r.d, (Gear)g),
               (double)drivetrain_get_shift_down_rpm(&r.d, (Gear)g));

    r.d.CurrentClutchState = CLUTCH_ENGAGING;
    out[0] = -1.0f;
    drivetrain_get_derivative(&r.d, out);
    pf("ax derivative", out[0]);

    drivetrain_set_state_gear(&r.d, SIXTH_GEAR);
    printf("ax setstate gear %s desired %s clutch %.9g state %s\n",
           gname(drivetrain_get_current_gear(&r.d)),
           gname(drivetrain_get_desired_gear(&r.d)),
           (double)r.d.State.clutch,
           cname(drivetrain_get_current_clutch_state(&r.d)));

    drivetrain_get_state(&r.d)->clutch = 0.375f;
    out[0] = -1.0f;
    drivetrain_get_state_array(&r.d, out);
    pf("ax getstate", out[0]);

    out[0] = 0.875f;
    drivetrain_set_state_array(&r.d, out);
    pf("ax setstate array", r.d.State.clutch);

    drivetrain_finalize_clutch_torque(&r.d);
    drivetrain_print_current_state(&r.d);
    pf("ax finalize clutch", r.d.State.clutch);

    printf("ax wired %d %d\n",
           drivetrain_get_engine(&r.d) == &r.e,
           drivetrain_get_drive_train_info(&r.d) == &r.dti);
}

static void s_frames(void)
{
    static const float spins[4] = { 80.0f, 81.0f, 84.0f, 85.0f };
    Rig r;
    float out[1];
    float dt = 1.0f / 60.0f;
    int frame;
    int i;
    char buf[32];

    reset_globals();
    WorldTimeElapsed = 1.0f / 60.0f;

    rig_make(&r, 1.0f, 6, 0.85f, 300.0f, 25.0f, 0, 0);
    for (i = 0; i < 4; i++) {
        r.w[i].State.w = spins[i];
        r.w[i].TouchingGround = 1;
    }
    r.d.CurrentGear = THIRD_GEAR;
    r.d.DesiredGear = THIRD_GEAR;
    r.d.CurrentClutchState = CLUTCH_ENGAGED;
    r.d.State.clutch = 1.0f;

    out[0] = 0.0f;

    for (frame = 0; frame < 12; frame++) {
        drivetrain_compute_auxiliaries(&r.d);
        drivetrain_guess_clutch_torque(&r.d);
        drivetrain_modify_clutch_torque(&r.d);
        drivetrain_finalize_clutch_torque(&r.d);
        drivetrain_set_desired_gear(&r.d, AUTOMATIC);

        drivetrain_get_derivative(&r.d, out);
        r.d.State.clutch += out[0] * dt;

        r.e.State.w += engine_get_angular_acceleration(&r.e) * dt;
        for (i = 0; i < 4; i++) {
            r.w[i].State.w += (r.w[i].AppliedTorque
                               / r.w[i].MomentOfInertia) * (dt * 0.01f);
            r.w[i].AppliedTorque = 0.0f;
        }
        r.e.RoadTorque = 0.0f;

        printf("fr %02d %s %s clutch %.9g diffw %.9g ew %.9g\n", frame,
               gname(r.d.CurrentGear), cname(r.d.CurrentClutchState),
               (double)r.d.State.clutch,
               (double)r.d.DifferentialAngularVelocity,
               (double)r.e.State.w);
        sprintf(buf, "fr %02d", frame);
        print_wheels(buf, r.w);
    }

    reset_globals();
}

int main(void)
{
    wheel_static_init();

    s_layout();
    s_shift_points();
    s_ctor();
    s_differential_velocity();
    s_slippage();
    s_set_differential();
    s_differential_acceleration();
    s_derivative();
    s_idling_matched();
    s_apply_clutch_torque();
    s_guess_clutch_torque();
    s_modify_clutch_torque();
    s_compute_auxiliaries();
    s_sport_gear();
    s_automatic();
    s_sport_shift();
    s_accessors();
    s_frames();

    return 0;
}
