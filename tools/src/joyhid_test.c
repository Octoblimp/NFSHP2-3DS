// Host test for joyhid.c: every 3DS key and stick, through joyhid_build,
// the ported ring and scanners and the generated tables, onto the event
// the map in joyhid.h says it raises. tools/joyhid_check.py builds and runs
// it.
//
// Where joystick_check.py holds the joystick layer to the image, this holds
// the map to its own promise: that A is the throttle and the menus' select,
// that X held turns ZL into the zone freeze rather than a downshift, and so
// on down the list, for configuration 30, with the default bindings and
// changed ones. The Be A Cop layout's calls (joyhid_cop_calls) go through
// the same path, as joyhid_read sends them.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bslotpool.h"
#include "joyevent.h"
#include "joyhid.h"
#include "joypad.h"
#include "realtime.h"

// ------------------------------------------------------------ the pool

static char pool_tag;

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *name,
                        int memoryPool)
{
    (void)slotSize;
    (void)numSlots;
    (void)name;
    (void)memoryPool;
    return (BSlotPool *)(void *)&pool_tag;
}

void *bSlotOMalloc(BSlotPool *pool)
{
    (void)pool;
    return calloc(1, sizeof(EventNode));
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    (void)pool;
    free(slot);
}

void bDeleteSlotPool(BSlotPool *pool)
{
    (void)pool;
}

// -------------------------------------------------------- the console

static JoyHidState pad;
static JoyHidCop   cop;

// joyhid_read's, with the console's state from the test.
static int32_t read_pad(int32_t port, uint8_t *buf)
{
    JoyHidState s = pad;

    if (port != 0)
        return 0;
    s.calls = joyhid_cop_calls(&cop, s.keys, s.race == JOYHID_LAYOUT_COP,
                               gJoyHidBindings.cop);
    joyhid_build(&s, buf);
    return 1;
}

// --------------------------------------------------------- the events

#define MAX_SEEN 64

static struct {
    JoyEvent ev;
    int      value;
} seen[MAX_SEEN];
static int nseen;

static void record(JoystickPort port, JoyEvent ev, uint8_t value, void *obj)
{
    (void)obj;
    if (port != 0 || nseen == MAX_SEEN)
        return;
    seen[nseen].ev = ev;
    seen[nseen].value = value;
    nseen++;
}

static const JoyEvent watched[] = {
    JOY_EVENT_SCROLL_UP, JOY_EVENT_SCROLL_DOWN, JOY_EVENT_START,
    JOY_EVENT_SELECT, JOY_EVENT_MENU_SELECT, JOY_EVENT_MENU_BACK,
    JOY_EVENT_MENU_HELP, JOY_EVENT_MENU_SQUARE, JOY_EVENT_MENU_ANALOG_LEFT,
    JOY_EVENT_MENU_ANALOG_RIGHT, JOY_EVENT_MENU_ANALOG_UP,
    JOY_EVENT_MENU_ANALOG_DOWN, JOY_EVENT_CAMERA_POV_CHANGE,
    JOY_EVENT_CAMERA_LOOKBACK, JOY_EVENT_ZONE_FREEZE, JOY_EVENT_ZONE_PREVIEW,
    JOY_EVENT_STEER, JOY_EVENT_STEER_ANALOG, JOY_EVENT_THROTTLE_ANALOG,
    JOY_EVENT_THROTTLE_ANALOG_ALTERNATE, JOY_EVENT_BRAKE_ANALOG,
    JOY_EVENT_BRAKE_ANALOG_ALTERNATE, JOY_EVENT_EBRAKE_ANALOG,
    JOY_EVENT_SHIFTUP, JOY_EVENT_SHIFTDOWN, JOY_EVENT_HONK_HORN,
    JOY_EVENT_NITRO_BOOST, JOY_EVENT_CYCLE_HUD,
    JOY_EVENT_REQUEST_HELICOPTER, JOY_EVENT_REQUEST_ROADBLOCK,
    JOY_EVENT_CARSEL_CHANGE_MODE, JOY_EVENT_CARSEL_ORBIT_LEFTRIGHT,
};
#define NWATCHED ((int)(sizeof(watched) / sizeof(watched[0])))

static int failures;

static void frame(void)
{
    nseen = 0;
    FrameCounter++;
    RealTimer += 67;
    ReadJoystickData();
    GenerateJoyEvents();
}

static int find(JoyEvent ev)
{
    int i;

    for (i = 0; i < nseen; i++)
        if (seen[i].ev == ev)
            return i;
    return -1;
}

static void dump(void)
{
    int i;

    for (i = 0; i < nseen; i++)
        printf("    saw %s %d\n", GetJoyEventName(seen[i].ev), seen[i].value);
}

// `ev` fired this frame, with a value in lo..hi.
static void expect(const char *what, JoyEvent ev, int lo, int hi)
{
    int i = find(ev);

    if (i >= 0 && seen[i].value >= lo && seen[i].value <= hi)
        return;
    failures++;
    if (i < 0)
        printf("FAIL %s: no %s\n", what, GetJoyEventName(ev));
    else
        printf("FAIL %s: %s is %d, not %d..%d\n", what, GetJoyEventName(ev),
               seen[i].value, lo, hi);
    dump();
}

static void expect_not(const char *what, JoyEvent ev)
{
    if (find(ev) < 0)
        return;
    failures++;
    printf("FAIL %s: %s fired\n", what, GetJoyEventName(ev));
    dump();
}

static void release(void)
{
    memset(&pad, 0, sizeof(pad));
    frame();
    frame();
}

// A press and its release, each a frame, then a rest.
static void press(const char *what, uint32_t keys, JoyEvent ev, int lo, int hi)
{
    pad.keys = keys;
    frame();
    expect(what, ev, lo, hi);
    release();
}

// A Be A Cop call from the shoulder `key`, held well past the call:
// `ev` on the second frame only, never a look back or an e-brake, never
// `shift`, and the camera change on the fourth, Y's release.
static void cop_call(const char *what, uint32_t key, JoyEvent ev,
                     JoyEvent shift)
{
    int i;

    pad.race = JOYHID_LAYOUT_COP;
    frame();
    pad.keys = key;
    for (i = 1; i <= 12; i++) {
        frame();
        if (i == 2)
            expect(what, ev, 1, 1);
        else
            expect_not(what, ev);
        if (i == 4)
            expect(what, JOY_EVENT_CAMERA_POV_CHANGE, 1, 1);
        else
            expect_not(what, JOY_EVENT_CAMERA_POV_CHANGE);
        expect_not(what, JOY_EVENT_CAMERA_LOOKBACK);
        expect_not(what, JOY_EVENT_EBRAKE_ANALOG);
        expect_not(what, shift);
        expect_not(what, JOY_EVENT_HONK_HORN);
    }
    pad.keys = 0;
    frame();
    expect_not(what, ev);
    expect_not(what, JOY_EVENT_CAMERA_LOOKBACK);
    expect_not(what, JOY_EVENT_EBRAKE_ANALOG);
    release();
}

int main(void)
{
    int i;

    joyevent_static_init();
    gJoypadRead = read_pad;
    InitJoystick();
    for (i = 0; i < NWATCHED; i++)
        AddJoyHandler(0, watched[i], record, NULL);

    // 32 matching reads before the type is believed (retail's count); the
    // 33rd frame reports it.
    for (i = 0; i < 34; i++)
        frame();
    if (GetJoystickType(0) != 121 || !IsJoystickPluggedIn(0)) {
        printf("FAIL type: port 0 is %d\n", GetJoystickType(0));
        failures++;
    }
    if (IsJoystickPluggedIn(1)) {
        printf("FAIL type: port 1 is plugged in as %d\n", GetJoystickType(1));
        failures++;
    }
    if (strcmp(GetJoystickButtonName(0, JOY_EVENT_THROTTLE_ANALOG), "CROSS")) {
        printf("FAIL config: throttle is %s\n",
               GetJoystickButtonName(0, JOY_EVENT_THROTTLE_ANALOG));
        failures++;
    }

    // The face buttons.
    pad.keys = JOYHID_A;
    frame();
    expect("A", JOY_EVENT_MENU_SELECT, 1, 1);
    expect("A", JOY_EVENT_THROTTLE_ANALOG, 250, 255);
    pad.keys = 0;
    frame();
    expect("A up", JOY_EVENT_THROTTLE_ANALOG, 0, 5);
    release();

    pad.keys = JOYHID_B;
    frame();
    expect("B", JOY_EVENT_MENU_SQUARE, 1, 1);
    expect("B", JOY_EVENT_BRAKE_ANALOG, 250, 255);
    release();

    // X: back in the menus on the press, the camera on the release.
    pad.keys = JOYHID_X;
    frame();
    expect("X", JOY_EVENT_MENU_BACK, 1, 1);
    expect_not("X", JOY_EVENT_CAMERA_POV_CHANGE);
    pad.keys = 0;
    frame();
    expect("X up", JOY_EVENT_CAMERA_POV_CHANGE, 1, 1);
    release();

    pad.keys = JOYHID_Y;
    frame();
    expect("Y", JOY_EVENT_HONK_HORN, 1, 1);
    expect("Y", JOY_EVENT_MENU_HELP, 1, 1);
    release();

    // The shoulders.
    press("L", JOYHID_L, JOY_EVENT_CAMERA_LOOKBACK, 1, 1);
    press("R", JOYHID_R, JOY_EVENT_EBRAKE_ANALOG, 250, 255);
    press("ZL", JOYHID_ZL, JOY_EVENT_SHIFTDOWN, 1, 1);
    press("ZR", JOYHID_ZR, JOY_EVENT_SHIFTUP, 1, 1);

    // X held, then ZL or ZR: the combo, and no gear change.
    pad.keys = JOYHID_X;
    frame();
    frame();
    pad.keys = JOYHID_X | JOYHID_ZL;
    frame();
    expect("X+ZL", JOY_EVENT_ZONE_FREEZE, 1, 1);
    expect_not("X+ZL", JOY_EVENT_SHIFTDOWN);
    pad.keys = JOYHID_X;
    frame();
    pad.keys = JOYHID_X | JOYHID_ZR;
    frame();
    expect("X+ZR", JOY_EVENT_ZONE_PREVIEW, 1, 1);
    expect_not("X+ZR", JOY_EVENT_SHIFTUP);
    release();

    // The race layout: X and Y swap, so X is the horn and Y the camera and
    // the combo modifier.
    pad.race = 1;
    pad.keys = JOYHID_X;
    frame();
    expect("race X", JOY_EVENT_HONK_HORN, 1, 1);
    expect_not("race X", JOY_EVENT_MENU_BACK);
    pad.keys = 0;
    frame();
    expect("race X up", JOY_EVENT_HONK_HORN, 0, 0);
    expect_not("race X up", JOY_EVENT_CAMERA_POV_CHANGE);
    pad.race = 1;
    frame();
    pad.keys = JOYHID_Y;
    frame();
    expect("race Y", JOY_EVENT_MENU_BACK, 1, 1);
    expect_not("race Y", JOY_EVENT_HONK_HORN);
    pad.keys = 0;
    frame();
    expect("race Y up", JOY_EVENT_CAMERA_POV_CHANGE, 1, 1);
    pad.race = 1;
    frame();
    pad.keys = JOYHID_Y;
    frame();
    frame();
    pad.keys = JOYHID_Y | JOYHID_ZL;
    frame();
    expect("race Y+ZL", JOY_EVENT_ZONE_FREEZE, 1, 1);
    expect_not("race Y+ZL", JOY_EVENT_SHIFTDOWN);
    release();

    // The frontend layout: B and X swap, so X is Square, car select's
    // orbit view, and B Triangle, the back; Y stays Circle, the help, as
    // main.c's keys have them (2026-10-16).
    pad.race = JOYHID_LAYOUT_FE;
    pad.keys = JOYHID_X;
    frame();
    expect("fe X", JOY_EVENT_CARSEL_CHANGE_MODE, 1, 1);
    expect("fe X", JOY_EVENT_MENU_SQUARE, 1, 1);
    expect_not("fe X", JOY_EVENT_MENU_BACK);
    expect_not("fe X", JOY_EVENT_HONK_HORN);
    release();
    pad.race = JOYHID_LAYOUT_FE;
    pad.keys = JOYHID_Y;
    frame();
    expect("fe Y", JOY_EVENT_MENU_HELP, 1, 1);
    expect_not("fe Y", JOY_EVENT_CARSEL_CHANGE_MODE);
    release();
    pad.race = JOYHID_LAYOUT_FE;
    pad.keys = JOYHID_B;
    frame();
    expect("fe B", JOY_EVENT_MENU_BACK, 1, 1);
    expect_not("fe B", JOY_EVENT_CARSEL_CHANGE_MODE);
    expect_not("fe B", JOY_EVENT_MENU_HELP);
    release();
    // The menu layout's B is still Square.
    pad.keys = JOYHID_B;
    frame();
    expect("menu B", JOY_EVENT_CARSEL_CHANGE_MODE, 1, 1);
    release();
    // The Circle Pad turns the car.
    pad.race = JOYHID_LAYOUT_FE;
    pad.cx = JOYHID_STICK_FULL;
    frame();
    expect("fe pad right", JOY_EVENT_CARSEL_ORBIT_LEFTRIGHT, 250, 255);
    release();

    // The D-pad.
    pad.keys = JOYHID_DDOWN;
    frame();
    expect("Down", JOY_EVENT_SCROLL_DOWN, 1, 1);
    expect("Down", JOY_EVENT_NITRO_BOOST, 1, 1);
    release();
    pad.keys = JOYHID_DUP;
    frame();
    expect("Up", JOY_EVENT_SCROLL_UP, 1, 1);
    expect("Up", JOY_EVENT_CYCLE_HUD, 1, 1);
    // Held: the repeat starts 25 frames after the press.
    for (i = 0; i < 26; i++)
        frame();
    expect("Up held", JOY_EVENT_SCROLL_UP, 2, 2);
    release();
    press("Left", JOYHID_DLEFT, JOY_EVENT_STEER, 0, 0);
    press("Right", JOYHID_DRIGHT, JOY_EVENT_STEER, 255, 255);

    // Be A Cop: L calls the roadblock and R the helicopter, Y then Y + ZR
    // or ZL then Y, and Y's release after; neither looks back, pulls the
    // e-brake or shifts, and a held key calls once.
    cop_call("cop L", JOYHID_L, JOY_EVENT_REQUEST_ROADBLOCK,
             JOY_EVENT_SHIFTUP);
    cop_call("cop R", JOYHID_R, JOY_EVENT_REQUEST_HELICOPTER,
             JOY_EVENT_SHIFTDOWN);
    // Both at once: the helicopter.
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_L | JOYHID_R;
    frame();
    frame();
    expect("cop both", JOY_EVENT_REQUEST_HELICOPTER, 1, 1);
    expect_not("cop both", JOY_EVENT_REQUEST_ROADBLOCK);
    release();
    // A press during a call is not kept.
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_R;
    frame();
    pad.keys = JOYHID_R | JOYHID_L;
    for (i = 0; i < 8; i++) {
        frame();
        expect_not("cop L in a call", JOY_EVENT_REQUEST_ROADBLOCK);
    }
    release();
    // Held from the race layout into the cop's: no call.
    pad.race = JOYHID_LAYOUT_RACE;
    pad.keys = JOYHID_R;
    frame();
    expect("race R", JOY_EVENT_EBRAKE_ANALOG, 250, 255);
    pad.race = JOYHID_LAYOUT_COP;
    for (i = 0; i < 6; i++) {
        frame();
        expect_not("cop R held over", JOY_EVENT_REQUEST_HELICOPTER);
        expect_not("cop R held over", JOY_EVENT_CAMERA_POV_CHANGE);
    }
    release();
    // A call, its key let go and pressed again: a second call.
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_L;
    frame();
    frame();
    expect("cop L first", JOY_EVENT_REQUEST_ROADBLOCK, 1, 1);
    frame();
    frame();
    pad.keys = 0;
    frame();
    pad.keys = JOYHID_L;
    frame();
    frame();
    expect("cop L again", JOY_EVENT_REQUEST_ROADBLOCK, 1, 1);
    release();
    // The D-pad steers in the cop's car too.
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_DLEFT;
    frame();
    expect("cop Left", JOY_EVENT_STEER, 0, 0);
    expect_not("cop Left", JOY_EVENT_REQUEST_HELICOPTER);
    release();
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_DRIGHT;
    frame();
    expect("cop Right", JOY_EVENT_STEER, 255, 255);
    expect_not("cop Right", JOY_EVENT_REQUEST_ROADBLOCK);
    release();
    // X is the horn, the cop's target.
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_X;
    frame();
    expect("cop X", JOY_EVENT_HONK_HORN, 1, 1);
    release();
    // D-pad Up keeps the HUD; ZL is the nitro (the user's, 2026-10-16)
    // and D-pad Down the downshift, ZL's old job.
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_DUP;
    frame();
    expect("cop Up", JOY_EVENT_CYCLE_HUD, 1, 1);
    release();
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_ZL;
    frame();
    expect("cop ZL", JOY_EVENT_NITRO_BOOST, 1, 1);
    expect_not("cop ZL", JOY_EVENT_SHIFTDOWN);
    expect_not("cop ZL", JOY_EVENT_REQUEST_HELICOPTER);
    release();
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_DDOWN;
    frame();
    expect("cop Down", JOY_EVENT_SHIFTDOWN, 1, 1);
    expect_not("cop Down", JOY_EVENT_NITRO_BOOST);
    release();
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_ZR;
    frame();
    expect("cop ZR", JOY_EVENT_SHIFTUP, 1, 1);
    release();
    // Y + Down, by hand, is still retail's combo: the helicopter.
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_Y;
    frame();
    frame();
    pad.keys = JOYHID_Y | JOYHID_DDOWN;
    frame();
    expect("cop Y+Down", JOY_EVENT_REQUEST_HELICOPTER, 1, 1);
    expect_not("cop Y+Down", JOY_EVENT_SHIFTDOWN);
    release();
    // A racer has no nitro and Down is free.
    pad.race = JOYHID_LAYOUT_RACE;
    pad.keys = JOYHID_DDOWN;
    frame();
    expect_not("race Down", JOY_EVENT_NITRO_BOOST);
    expect_not("race Down", JOY_EVENT_SHIFTDOWN);
    release();

    // Changed bindings: the racer's throttle on ZR (shift up takes A), the
    // cop's roadblock on X (the horn takes L) and boost on B (the brake
    // takes ZL).
    joyhid_bind(gJoyHidBindings.racer, JOYHID_ACT_THROTTLE, JOYHID_BIND_ZR);
    joyhid_bind(gJoyHidBindings.cop, JOYHID_ACT_ROADBLOCK, JOYHID_BIND_X);
    joyhid_bind(gJoyHidBindings.cop, JOYHID_ACT_BOOST, JOYHID_BIND_B);
    pad.race = JOYHID_LAYOUT_RACE;
    pad.keys = JOYHID_ZR;
    frame();
    expect("rebound race ZR", JOY_EVENT_THROTTLE_ANALOG, 250, 255);
    expect_not("rebound race ZR", JOY_EVENT_SHIFTUP);
    release();
    pad.race = JOYHID_LAYOUT_RACE;
    pad.keys = JOYHID_A;
    frame();
    expect("rebound race A", JOY_EVENT_SHIFTUP, 1, 1);
    expect_not("rebound race A", JOY_EVENT_THROTTLE_ANALOG);
    release();
    cop_call("rebound cop X", JOYHID_X, JOY_EVENT_REQUEST_ROADBLOCK,
             JOY_EVENT_SHIFTUP);
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_L;
    frame();
    expect("rebound cop L", JOY_EVENT_HONK_HORN, 1, 1);
    expect_not("rebound cop L", JOY_EVENT_REQUEST_ROADBLOCK);
    release();
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_B;
    frame();
    expect("rebound cop B", JOY_EVENT_NITRO_BOOST, 1, 1);
    expect_not("rebound cop B", JOY_EVENT_BRAKE_ANALOG);
    release();
    pad.race = JOYHID_LAYOUT_COP;
    pad.keys = JOYHID_ZL;
    frame();
    expect("rebound cop ZL", JOY_EVENT_BRAKE_ANALOG, 250, 255);
    release();
    // The menus never move: A is still select and B Square.
    pad.race = JOYHID_LAYOUT_MENU;
    pad.keys = JOYHID_A;
    frame();
    expect("rebound menu A", JOY_EVENT_MENU_SELECT, 1, 1);
    release();
    joyhid_default_bindings(&gJoyHidBindings);

    // The controls file (joyconfig.h's controls.bin): changed tables come
    // back as they went; a short, long, foreign, newer or broken file is
    // refused and leaves the tables alone.
    {
        JoyHidBindings b, back, def;
        uint8_t        file[JOYHID_FILE_SIZE + 1];
        uint8_t        bad[JOYHID_FILE_SIZE];

        joyhid_default_bindings(&def);
        b = def;
        joyhid_bind(b.racer, JOYHID_ACT_HUD, JOYHID_BIND_Y);
        joyhid_bind(b.cop, JOYHID_ACT_EBRAKE, JOYHID_BIND_DDOWN);
        joyhid_bindings_pack(&b, file);
        if (memcmp(file, "HP2K", 4) != 0 || file[4] != JOYHID_FILE_VERSION
            || file[5] != JOYHID_ACT_COUNT) {
            printf("FAIL pack: header %02x %02x %02x %02x %u %u\n", file[0],
                   file[1], file[2], file[3], file[4], file[5]);
            failures++;
        }
        memset(&back, 0, sizeof back);
        if (!joyhid_bindings_unpack(file, JOYHID_FILE_SIZE, &back)
            || memcmp(&back, &b, sizeof b) != 0) {
            printf("FAIL unpack: the packed tables did not come back\n");
            failures++;
        }
        back = def;
        if (joyhid_bindings_unpack(file, JOYHID_FILE_SIZE - 1, &back)
            || joyhid_bindings_unpack(file, JOYHID_FILE_SIZE + 1, &back)
            || memcmp(&back, &def, sizeof def) != 0) {
            printf("FAIL unpack: a file of the wrong size was taken\n");
            failures++;
        }
        for (int i = 0; i < 4; i++) {
            memcpy(bad, file, sizeof bad);
            if (i == 0) bad[0] = 'X';                      // not ours
            if (i == 1) bad[4] = JOYHID_FILE_VERSION + 1;  // newer
            if (i == 2) bad[5] = JOYHID_ACT_COUNT - 1;     // fewer actions
            if (i == 3) bad[6] = bad[7];                   // a key twice
            if (joyhid_bindings_unpack(bad, sizeof bad, &back)
                || memcmp(&back, &def, sizeof def) != 0) {
                printf("FAIL unpack: bad file %d was taken\n", i);
                failures++;
            }
        }

        // The page's guard: a car can always go and stop. The racer's
        // e-brake to A would hand the throttle R, which is fine; the
        // cop's e-brake has no key, so A or B to it would leave the
        // throttle or the brake on none.
        if (!joyhid_bind_keeps_drive(def.racer, JOYHID_ACT_EBRAKE,
                                     JOYHID_BIND_A)
            || joyhid_bind_keeps_drive(def.cop, JOYHID_ACT_EBRAKE,
                                       JOYHID_BIND_A)
            || joyhid_bind_keeps_drive(def.cop, JOYHID_ACT_EBRAKE,
                                       JOYHID_BIND_B)
            || !joyhid_bind_keeps_drive(def.cop, JOYHID_ACT_EBRAKE,
                                        JOYHID_BIND_Y)
            || !joyhid_bind_keeps_drive(def.cop, JOYHID_ACT_THROTTLE,
                                        JOYHID_BIND_B)) {
            printf("FAIL keeps_drive\n");
            failures++;
        }
        b = def;
        (void)joyhid_bind_keeps_drive(b.cop, JOYHID_ACT_EBRAKE,
                                      JOYHID_BIND_A);
        if (memcmp(&b, &def, sizeof def) != 0) {
            printf("FAIL keeps_drive changed the table\n");
            failures++;
        }
    }

    press("START", JOYHID_START, JOY_EVENT_START, 1, 1);
    press("SELECT", JOYHID_SELECT, JOY_EVENT_SELECT, 1, 1);

    // The Circle Pad.
    pad.cx = -JOYHID_STICK_FULL;
    frame();
    expect("pad left", JOY_EVENT_STEER_ANALOG, 0, 5);
    expect("pad left", JOY_EVENT_MENU_ANALOG_LEFT, 1, 1);
    release();
    pad.cx = JOYHID_STICK_FULL;
    frame();
    expect("pad right", JOY_EVENT_STEER_ANALOG, 250, 255);
    expect("pad right", JOY_EVENT_MENU_ANALOG_RIGHT, 1, 1);
    release();
    pad.cx = 10;
    frame();
    expect_not("pad in the dead zone", JOY_EVENT_STEER_ANALOG);
    release();
    pad.cy = JOYHID_STICK_FULL;
    frame();
    expect("pad up", JOY_EVENT_MENU_ANALOG_UP, 1, 1);
    release();
    pad.cy = -JOYHID_STICK_FULL;
    frame();
    expect("pad down", JOY_EVENT_MENU_ANALOG_DOWN, 1, 1);
    release();

    // The C-Stick.
    pad.sy = JOYHID_STICK_FULL;
    frame();
    expect("C-Stick up", JOY_EVENT_THROTTLE_ANALOG_ALTERNATE, 250, 255);
    release();
    pad.sy = -JOYHID_STICK_FULL;
    frame();
    expect("C-Stick down", JOY_EVENT_BRAKE_ANALOG_ALTERNATE, 250, 255);
    release();

    // The Circle Pad as the menus' D-pad (TASKS 42).
    {
        static const struct {
            const char *what;
            int32_t     cx, cy;
            uint32_t    want;
        } steps[] = {
            { "menu pad centred",          0,    0,    0 },
            { "menu pad short of a press", 96,   0,    0 },
            { "menu pad right",            97,   0,    JOYHID_DRIGHT },
            { "menu pad right held",       156,  20,   0 },
            { "menu pad eased off",        48,   0,    0 },
            { "menu pad out from 48",      120,  0,    0 },
            { "menu pad let go",           47,   0,    0 },
            { "menu pad short up",         0,    90,   0 },
            { "menu pad short up let go",  0,    0,    0 },
            { "menu pad right again",      120,  0,    JOYHID_DRIGHT },
            { "menu pad back to centre",   0,    0,    0 },
            { "menu pad left",             -130, 10,   JOYHID_DLEFT },
            { "menu pad left to up",       -40,  140,  JOYHID_DUP },
            { "menu pad up held",          30,   60,   0 },
            { "menu pad up eased to 48",   0,    48,   0 },
            { "menu pad up out again",     0,    130,  0 },
            { "menu pad up to right",      150,  47,   JOYHID_DRIGHT },
            { "menu pad centre",           0,    0,    0 },
            { "menu pad down",             0,    -100, JOYHID_DDOWN },
            { "menu pad down held",        90,   -95,  0 },
            { "menu pad centre again",     0,    0,    0 },
            { "menu pad diagonal",         110,  110,  JOYHID_DRIGHT },
            { "menu pad centre last",      0,    0,    0 },
            { "menu pad steeper up",       100,  110,  JOYHID_DUP },
        };
        JoyHidMenuPad mp;

        memset(&mp, 0, sizeof mp);
        for (size_t i = 0; i < sizeof steps / sizeof steps[0]; i++) {
            uint32_t got = joyhid_menu_pad(&mp, steps[i].cx, steps[i].cy);

            if (got != steps[i].want) {
                printf("FAIL %s: %#x, want %#x\n", steps[i].what,
                       (unsigned)got, (unsigned)steps[i].want);
                failures++;
            }
        }
    }

    // A pad sent over the wire (bytes 2 to 7) comes back as built, for
    // every set of keys, each layout and a few stick readings.
    {
        static const uint32_t keys[] = {
            JOYHID_A, JOYHID_B, JOYHID_SELECT, JOYHID_START, JOYHID_DRIGHT,
            JOYHID_DLEFT, JOYHID_DUP, JOYHID_DDOWN, JOYHID_R, JOYHID_L,
            JOYHID_X, JOYHID_Y, JOYHID_ZL, JOYHID_ZR,
        };
        static const int32_t sticks[][4] = {
            { 0, 0, 0, 0 }, { 156, -156, 40, 90 }, { -73, 12, -144, 144 },
        };
        int wrong = 0;

        for (uint32_t set = 0; set < 1u << 14; set++) {
            JoyHidState s;
            uint8_t built[32];
            uint8_t back[32];

            memset(&s, 0, sizeof s);
            for (size_t k = 0; k < 14; k++)
                if (set & 1u << k)
                    s.keys |= keys[k];
            s.race = (int32_t)(set % 4);
            if (set % 5 == 1)
                s.calls = JOYHID_DS2_TRIANGLE;
            else if (set % 5 == 2)
                s.calls = JOYHID_DS2_TRIANGLE | JOYHID_DS2_L2;
            else if (set % 5 == 3)
                s.calls = JOYHID_DS2_TRIANGLE | JOYHID_DS2_R2;
            s.cx = sticks[set % 3][0];
            s.cy = sticks[set % 3][1];
            s.sx = sticks[set % 3][2];
            s.sy = sticks[set % 3][3];
            joyhid_build(&s, built);
            joyhid_from_wire(built + 2, back);
            if (memcmp(built, back, 32) != 0 && wrong++ == 0) {
                printf("FAIL from_wire: keys %#x layout %d differ\n",
                       (unsigned)s.keys, (int)s.race);
                failures++;
            }
        }
    }

    CloseJoystick();
    if (failures) {
        printf("%d failed\n", failures);
        return 1;
    }
    printf("joyhid: every key and stick reaches its event\n");
    return 0;
}
