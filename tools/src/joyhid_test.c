// Host test for joyhid.c: every 3DS key and stick, through joyhid_build,
// the ported ring and scanners and the generated tables, onto the event
// the map in joyhid.h says it raises. tools/joyhid_check.py builds and runs
// it.
//
// Where joystick_check.py holds the joystick layer to the image, this holds
// the map to its own promise: that A is the throttle and the menus' select,
// that X held turns ZL into the zone freeze rather than a downshift, and so
// on down the list, for configuration 30.

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

static void read_pad(int32_t port, uint8_t *buf)
{
    if (port == 0)
        joyhid_build(&pad, buf);
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

int main(void)
{
    int i;

    joyevent_static_init();
    gJoypadRead = read_pad;
    InitJoystick();
    for (i = 0; i < NWATCHED; i++)
        AddJoyHandler(0, watched[i], record, NULL);

    // Ten matching reads before the type is believed; the eleventh frame
    // reports it.
    for (i = 0; i < 12; i++)
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

    CloseJoystick();
    if (failures) {
        printf("%d failed\n", failures);
        return 1;
    }
    printf("joyhid: every key and stick reaches its event\n");
    return 0;
}
