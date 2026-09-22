// Transcript harness for CarDriver, and for DriveTarget's layout and
// assignment. Cross-checked by tools/cardriver_check.py, which models the
// same behaviour from the disassembly without reading this file.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cardriver.h"
#include "drivetarget.h"

// drivetarget.c reads the frame tick, which engine.c owns in the handheld
// build. Defined here for the same reason drivetarget_test.c defines its
// own: linking engine.c would drag Table, CarTypeInfo and Wheel in behind
// it, and nothing in this harness calls the code that reads it.
int32_t WorldTimer = 0;

// ------------------------------------------------------------- the layout

static void scenario_layout(void)
{
    printf("[layout]\n");
    printf("sizeof CarDriver %zu\n", sizeof(CarDriver));
    printf("sizeof DriveTarget %zu\n", sizeof(DriveTarget));
    printf("sizeof Gear %zu\n", sizeof(Gear));

#define OFF(t, f) printf("off %-20s %zu\n", #t "." #f, offsetof(t, f))
    OFF(CarDriver, MyDriveTarget); OFF(CarDriver, Steering);
    OFF(CarDriver, Throttle); OFF(CarDriver, Brake);
    OFF(CarDriver, EBrake); OFF(CarDriver, DesiredGear);
    OFF(CarDriver, SportGear); OFF(CarDriver, NitroFlag);
    OFF(CarDriver, _vtable);

    OFF(DriveTarget, NumPoints); OFF(DriveTarget, Points);
    OFF(DriveTarget, CalculatedSpeed); OFF(DriveTarget, Route);
    OFF(DriveTarget, RoutePointNumber); OFF(DriveTarget, DrivingLine);
    OFF(DriveTarget, TType); OFF(DriveTarget, WhichPointIPicked);
    OFF(DriveTarget, WhichPointIPickedCalculationTime);
    OFF(DriveTarget, WhichPointIPickedTime); OFF(DriveTarget, Length);
#undef OFF

#define ARR(t, f) printf("arr %-20s %zu\n", #t "." #f, \
                         sizeof(((t *)0)->f))
    ARR(DriveTarget, Points); ARR(DriveTarget, CalculatedSpeed);
    ARR(DriveTarget, Route); ARR(DriveTarget, RoutePointNumber);
    ARR(DriveTarget, DrivingLine);
#undef ARR

    // The element strides, because an extent alone does not pin them:
    // Route[20] of int8 and Route[5] of int32 are both 20 bytes.
    printf("stride Points %zu\n",
           (size_t)((char *)&((DriveTarget *)0)->Points[1]
                    - (char *)&((DriveTarget *)0)->Points[0]));
    printf("stride CalculatedSpeed %zu\n",
           (size_t)((char *)&((DriveTarget *)0)->CalculatedSpeed[1]
                    - (char *)&((DriveTarget *)0)->CalculatedSpeed[0]));
    printf("stride Route %zu\n",
           (size_t)((char *)&((DriveTarget *)0)->Route[1]
                    - (char *)&((DriveTarget *)0)->Route[0]));
    printf("stride RoutePointNumber %zu\n",
           (size_t)((char *)&((DriveTarget *)0)->RoutePointNumber[1]
                    - (char *)&((DriveTarget *)0)->RoutePointNumber[0]));
    printf("stride DrivingLine %zu\n",
           (size_t)((char *)&((DriveTarget *)0)->DrivingLine[1]
                    - (char *)&((DriveTarget *)0)->DrivingLine[0]));

    // Widths and signedness, which the offsets alone do not pin: a
    // 32-bit Steering with no pad after it puts every following field in
    // exactly the same place, and a uint8_t NumPoints reads the same byte
    // as an int8_t one right up until the byte has its top bit set.
    {
        CarDriver *w = calloc(1, sizeof(CarDriver));
        DriveTarget *q = &w->MyDriveTarget;
        printf("width Steering %zu\n", sizeof(w->Steering));
        printf("width NitroFlag %zu\n", sizeof(w->NitroFlag));
        printf("width NumPoints %zu\n", sizeof(q->NumPoints));
        printf("width Route %zu\n", sizeof(q->Route[0]));
        printf("width DrivingLine %zu\n", sizeof(q->DrivingLine[0]));
        printf("width RoutePointNumber %zu\n", sizeof(q->RoutePointNumber[0]));
        // Assigning an all-ones pattern and asking whether it came back
        // negative is the cheapest signedness probe there is.
        w->Steering = (uint16_t)0xffffu;  q->NumPoints = (int8_t)0xff;
        q->Route[0] = (int8_t)0xff;       q->DrivingLine[0] = (int8_t)0xff;
        q->RoutePointNumber[0] = (int16_t)0xffff;
        // Via a wide signed variable rather than comparing the field
        // against 0 directly: the integral promotion still carries the
        // sign, and -Wtype-limits stops objecting that an unsigned field
        // can never be negative -- which is the answer being measured.
#define SIGNED(name, expr) do { long long sv_ = (expr); \
            printf("signed %s %d\n", name, sv_ < 0); } while (0)
        SIGNED("Steering", w->Steering);
        SIGNED("NumPoints", q->NumPoints);
        SIGNED("Route", q->Route[0]);
        SIGNED("DrivingLine", q->DrivingLine[0]);
        SIGNED("RoutePointNumber", q->RoutePointNumber[0]);
#undef SIGNED
        // The fourth lane of a point is bVector3's `pad`, not a `w`. It
        // is never meaningful, but naming it is part of the claim.
        printf("point pad %.9g\n", q->Points[0].pad);
        free(w);
    }

    // MyDriveTarget is at offset 0, which is what makes SetTarget's tail
    // call and GetDriveTarget's `move v0,a0` work. Show it rather than
    // assert it.
    CarDriver *d = calloc(1, sizeof(CarDriver));
    printf("alias %d\n", (void *)&d->MyDriveTarget == (void *)d);
    printf("alias get %d\n", (void *)cardriver_get_drive_target(d) == (void *)d);
    free(d);
}

// --------------------------------------------------------- the constructor

// A byte pattern that is not zero anywhere, so "the constructor cleared
// this" and "the constructor left this alone" are distinguishable.
static void scribble(void *p, size_t n, unsigned seed)
{
    unsigned char *b = p;
    for (size_t i = 0; i < n; i++) b[i] = (unsigned char)(seed + i * 7 + 1);
}

static unsigned long sum(const void *p, size_t off, size_t n)
{
    const unsigned char *b = (const unsigned char *)p + off;
    unsigned long s = 0;
    for (size_t i = 0; i < n; i++) s += b[i];
    return s;
}

static void scenario_ctor(void)
{
    printf("[ctor]\n");

    CarDriver *d = malloc(sizeof(CarDriver));
    scribble(d, sizeof(CarDriver), 0);

    // What SportGear held before construction, so the transcript can show
    // that it still holds it afterwards.
    Gear before = d->SportGear;
    printf("sportgear before %d\n", before);

    cardriver_init(d);

    printf("vtable %08x\n", d->_vtable);
    printf("drivetarget zeroed %lu\n", sum(d, 0, sizeof(DriveTarget)));
    printf("steering %u\n", d->Steering);
    printf("throttle %.9g\n", d->Throttle);
    printf("brake %.9g\n", d->Brake);
    printf("ebrake %.9g\n", d->EBrake);
    printf("desiredgear %d\n", d->DesiredGear);
    printf("nitro %d\n", d->NitroFlag);
    // The one field the constructor does not touch.
    printf("sportgear after %d\n", d->SportGear);
    printf("sportgear unchanged %d\n", d->SportGear == before);

    // A second run over a differently scribbled object: everything the
    // constructor writes must land on the same values, and SportGear must
    // again survive -- with a different value, which is what shows it is
    // the allocation's and not a constant.
    scribble(d, sizeof(CarDriver), 99);
    before = d->SportGear;
    cardriver_init(d);
    printf("second sportgear %d unchanged %d\n", d->SportGear,
           d->SportGear == before);
    printf("second desiredgear %d nitro %d steering %u\n",
           d->DesiredGear, d->NitroFlag, d->Steering);

    // The destructor rewrites the vtable and does nothing else, so
    // scribble over it and watch it come back.
    d->_vtable = 0xdeadbeefu;
    cardriver_fini(d);
    printf("fini vtable %08x\n", d->_vtable);
    printf("fini desiredgear %d\n", d->DesiredGear);

    free(d);
}

// ------------------------------------------------------- the input record

static void scenario_inputs(void)
{
    printf("[inputs]\n");

    CarDriver *d = calloc(1, sizeof(CarDriver));

    static const uint16_t bams[] = { 0, 1, 0x4000, 0x8000, 0xc000, 0xffff };
    for (size_t i = 0; i < sizeof(bams) / sizeof(bams[0]); i++) {
        cardriver_set_steering(d, bams[i]);
        // lhu, so a BAM past the half turn reads back as a large positive
        // number and not as a negative angle.
        printf("steering %u -> %u\n", bams[i], cardriver_get_steering(d));
    }

    static const float pedals[] = { 0.0f, 1.0f, 0.5f, -1.0f, 1e30f, -0.0f };
    for (size_t i = 0; i < sizeof(pedals) / sizeof(pedals[0]); i++) {
        cardriver_set_throttle(d, pedals[i]);
        cardriver_set_brake(d, -pedals[i]);
        cardriver_set_ebrake(d, pedals[i] * 2.0f);
        printf("pedals %.9g %.9g %.9g\n", cardriver_get_throttle(d),
               cardriver_get_brake(d), cardriver_get_ebrake(d));
    }

    static const int32_t gears[] = { -1, 0, 1, 2, 6, 0x7fffffff };
    for (size_t i = 0; i < sizeof(gears) / sizeof(gears[0]); i++) {
        cardriver_set_desired_gear(d, gears[i]);
        cardriver_set_sport_gear(d, -gears[i]);
        printf("gears %d %d\n", cardriver_get_desired_gear(d),
               cardriver_get_sport_gear(d));
    }

    // `lhu` reads two bytes. Write four and watch the top two vanish --
    // which a 32-bit Steering would not do.
    {
        uint32_t all = 0xfeedfaceu;
        memcpy((unsigned char *)d + 528, &all, 4);
        printf("poke32 %u\n", cardriver_get_steering(d));
    }

    // Values that do not fit in a byte, so a narrowed NitroFlag shows up.
    static const int32_t nitros[] = { 0, 1, 2, -1, 256, 12345, -70000 };
    for (size_t i = 0; i < sizeof(nitros) / sizeof(nitros[0]); i++) {
        cardriver_set_nitro(d, nitros[i]);
        // `sw a1,552(a0)` -- the whole word goes in, so this is not
        // narrowed to 0 or 1 on the way through.
        printf("nitro %d -> %d\n", nitros[i], cardriver_get_nitro(d));
    }

    // Each setter must touch exactly one field. Set them all to distinct
    // values and read the lot back.
    cardriver_set_steering(d, 0x1234);
    cardriver_set_throttle(d, 0.25f);
    cardriver_set_brake(d, 0.5f);
    cardriver_set_ebrake(d, 0.75f);
    cardriver_set_desired_gear(d, 3);
    cardriver_set_sport_gear(d, 4);
    cardriver_set_nitro(d, 1);
    printf("all %u %.9g %.9g %.9g %d %d %d\n",
           cardriver_get_steering(d), cardriver_get_throttle(d),
           cardriver_get_brake(d), cardriver_get_ebrake(d),
           cardriver_get_desired_gear(d), cardriver_get_sport_gear(d),
           cardriver_get_nitro(d));

    free(d);
}

// ------------------------------------------------------------- the target

static void fill_target(DriveTarget *t, int seed)
{
    memset(t, 0, sizeof(*t));
    t->NumPoints = (int8_t)(seed + 7);
    for (int i = 0; i < DRIVETARGET_MAX_POINTS; i++) {
        t->Points[i].x = (float)(seed * 100 + i);
        t->Points[i].y = (float)(seed * 100 + i) + 0.5f;
        t->Points[i].z = (float)-(seed * 100 + i);
        t->CalculatedSpeed[i] = (float)(i) * 1.25f + (float)seed;
        t->Route[i] = (int8_t)(i - 10);
        t->RoutePointNumber[i] = (int16_t)(1000 + i * seed);
        t->DrivingLine[i] = (int8_t)(3 - i);
    }
    t->TType = 5 + seed;
    t->WhichPointIPicked = (int8_t)(seed - 3);
    t->WhichPointIPickedCalculationTime = 12345 + seed;
    t->WhichPointIPickedTime = 999 - seed;
    t->Length = 42.5f * (float)seed;
}

static void print_target(const char *tag, const DriveTarget *t)
{
    printf("%s numpoints %d ttype %d picked %d ptime %d atime %d len %.9g\n",
           tag, t->NumPoints, t->TType, t->WhichPointIPicked,
           t->WhichPointIPickedCalculationTime, t->WhichPointIPickedTime,
           t->Length);
    for (int i = 0; i < DRIVETARGET_MAX_POINTS; i += 7) {
        printf("%s p%d %.9g %.9g %.9g spd %.9g route %d rpn %d dl %d\n",
               tag, i, t->Points[i].x, t->Points[i].y, t->Points[i].z,
               t->CalculatedSpeed[i], t->Route[i], t->RoutePointNumber[i],
               t->DrivingLine[i]);
    }
}

static void scenario_target(void)
{
    printf("[target]\n");

    CarDriver *d = malloc(sizeof(CarDriver));
    scribble(d, sizeof(CarDriver), 31);
    cardriver_init(d);

    DriveTarget *src = malloc(sizeof(DriveTarget));
    fill_target(src, 2);

    cardriver_set_target(d, src);
    print_target("copied", cardriver_get_drive_target(d));

    // The copy is by value, so moving the source afterwards must not move
    // what the driver holds.
    fill_target(src, 9);
    print_target("src9", src);
    print_target("still", cardriver_get_drive_target(d));

    // And the record is copied whole, not field by field, so a second
    // assignment overwrites every byte including the tail padding.
    cardriver_set_target(d, src);
    printf("second copy identical %d\n",
           memcmp(cardriver_get_drive_target(d), src,
                  sizeof(DriveTarget)) == 0);

    // The assignment must not reach past MyDriveTarget into the inputs.
    cardriver_set_steering(d, 0x0abc);
    cardriver_set_throttle(d, 0.125f);
    cardriver_set_sport_gear(d, 11);
    cardriver_set_target(d, src);
    printf("inputs survive %u %.9g %d\n", cardriver_get_steering(d),
           cardriver_get_throttle(d), cardriver_get_sport_gear(d));

    // A target with the top bit set in every byte-wide field, so a
    // uint8_t where the image uses `lb` stops being invisible.
    memset(src, 0, sizeof(*src));
    src->NumPoints = (int8_t)0x80;
    src->WhichPointIPicked = (int8_t)0xff;
    src->Route[0] = (int8_t)0x81;
    src->DrivingLine[0] = (int8_t)0xc0;
    src->RoutePointNumber[0] = (int16_t)0x8001;
    cardriver_set_target(d, src);
    {
        const DriveTarget *g = cardriver_get_drive_target(d);
        printf("signbits %d %d %d %d %d\n", g->NumPoints,
               g->WhichPointIPicked, g->Route[0], g->DrivingLine[0],
               g->RoutePointNumber[0]);
    }

    // The return value of the assignment is the destination.
    DriveTarget *r = drivetarget_assign(cardriver_get_drive_target(d), src);
    printf("assign returns dst %d\n", r == cardriver_get_drive_target(d));

    free(src);
    free(d);
}

// ------------------------------------------------------------- the stubs

static void scenario_stubs(void)
{
    printf("[stubs]\n");

    // Every input set to something non-zero first: a stub that quietly
    // writes a zero over an already-zero field is invisible otherwise.
    CarDriver *d = malloc(sizeof(CarDriver));
    scribble(d, sizeof(CarDriver), 17);
    cardriver_init(d);
    cardriver_set_steering(d, 0x7f7f);
    cardriver_set_throttle(d, 0.625f);
    cardriver_set_brake(d, 0.375f);
    cardriver_set_ebrake(d, 0.875f);
    cardriver_set_desired_gear(d, 5);
    cardriver_set_sport_gear(d, 6);
    // Not 1: StartHonkHorn writing a 1 over a 1 would be invisible.
    cardriver_set_nitro(d, 3);
    unsigned long before = sum(d, 0, sizeof(CarDriver));

    printf("steer_to_point %d\n", cardriver_get_steer_to_point(d) == NULL);
    printf("desired_time_to_speed %.9g\n",
           cardriver_get_desired_time_to_speed(d));
    printf("desired_speed %.9g\n", cardriver_get_desired_speed(d));
    printf("is_honking %d\n", cardriver_is_honking(d));

    DriveTarget *t = calloc(1, sizeof(DriveTarget));
    fill_target(t, 4);
    printf("max_speed_to_target %.9g\n", cardriver_max_speed_to_target(d, t));
    free(t);

    // The setter drops its argument on the floor: the getter still says
    // NULL, and nothing in the object moved.
    bVector2 p = { 1.0f, 2.0f };
    cardriver_set_steer_to_point(d, &p);
    printf("after set_steer_to_point %d\n",
           cardriver_get_steer_to_point(d) == NULL);

    cardriver_set_physics_mode(d, 3);
    cardriver_clear_steering_memory(d);
    cardriver_zero_steering_memory(d);
    cardriver_start_honk_horn(d);
    printf("honking after start %d\n", cardriver_is_honking(d));
    cardriver_stop_honk_horn(d);
    cardriver_add_joy_handlers(d);
    cardriver_remove_joy_handlers(d);

    printf("object unchanged %d\n", sum(d, 0, sizeof(CarDriver)) == before);

    free(d);
}

int main(void)
{
    scenario_layout();
    scenario_ctor();
    scenario_inputs();
    scenario_target();
    scenario_stubs();
    return 0;
}
