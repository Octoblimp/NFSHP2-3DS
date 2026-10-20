// eastereggs -- see eastereggs.h.

#include "eastereggs.h"

#include "joyeventid.h"

EasterEggs TheEasterEggs;

// The table at 0x0031d828, read out of SLES_507.31: each code's eight
// presses, then Type, Param, Group, LanguageID, On and Kept. The comment
// over each is its LanguageID's English. Every On is 0 on the disc.
#define L1 JOY_EVENT_CHEAT_L1
#define L2 JOY_EVENT_CHEAT_L2
#define R1 JOY_EVENT_CHEAT_R1
#define R2 JOY_EVENT_CHEAT_R2
#define DL JOY_EVENT_CHEAT_DPADL
#define DR JOY_EVENT_CHEAT_DPADR
#define SQ JOY_EVENT_CHEAT_SQUARE
#define TR JOY_EVENT_CHEAT_TRIANGLE
#define NO JOY_EVENT_NULL
#define T_EGG        EASTEREGG_TYPE_EGG
#define T_CAR        EASTEREGG_TYPE_CAR
#define T_COP_CAR    EASTEREGG_TYPE_COP_CAR
#define T_TRACK      EASTEREGG_TYPE_TRACK
#define T_TRACK_BACK EASTEREGG_TYPE_TRACK_BACK

EasterEggCode TheEasterEggCodes[EASTEREGGS_NUM_CODES] = {
    // 0: Motion Blur
    { { L2, L1, R1, SQ, R1, R1, R1, L1 }, T_EGG, 0, 1, 990114, 0, 0 },
    // 1: Black & White
    { { R1, L1, DL, TR, DL, DL, DL, L1 }, T_EGG, 1, 1, 990120, 0, 0 },
    // 2: Heavy Fog
    { { TR, SQ, DR, R2, DR, DR, DR, SQ }, T_EGG, 2, 1, 990115, 0, 0 },
    // 3: R/C Car
    { { DR, TR, L1, R1, L1, L1, L1, TR }, T_EGG, 3, 1, 990113, 0, 0 },
    // 4: Video Mode
    { { L1, R1, DR, SQ, DR, DR, DR, R1 }, T_EGG, 4, 1, 990122, 0, 0 },
    // 5: Pet Helicopter
    { { NO, NO, NO, NO, NO, NO, NO, NO }, T_EGG, 5, 0, 990121, 0, 0 },
    // 6: Championship Bonus Event
    { { L1, SQ, R2, R2, R2, R1, L1, SQ }, T_EGG, 6, 0, 990123, 0, 1 },
    // 7: Ultimate Racer Bonus Event
    { { DR, SQ, DL, DL, DL, R2, DR, SQ }, T_EGG, 7, 0, 990124, 0, 1 },
    // 8: Chrome Cars
    { { L2, R2, DL, SQ, DL, DL, DL, R2 }, T_EGG, 8, 0, 990125, 0, 0 },
    // 9: McLaren F1
    { { TR, L1, TR, L1, R1, DL, R1, DL }, T_CAR, 7, 0, 41104, 0, 1 },
    // 10: McLaren F1: NFS
    { { DL, TR, TR, TR, L2, SQ, SQ, TR }, T_CAR, 8, 0, 41203, 0, 1 },
    // 11: McLaren F1 LM
    { { SQ, L1, SQ, L1, TR, DR, TR, DR }, T_CAR, 9, 0, 41105, 0, 1 },
    // 12: McLaren F1 LM: NFS
    { { R1, SQ, SQ, SQ, R2, DL, DL, SQ }, T_CAR, 10, 0, 41204, 0, 1 },
    // 13: Mercedes CLK-GTR
    { { R2, R1, R2, R1, DL, TR, DL, TR }, T_CAR, 5, 0, 41103, 0, 1 },
    // 14: Mercedes CLK-GTR: NFS
    { { TR, DL, DL, DL, L1, L2, L2, DL }, T_CAR, 6, 0, 41202, 0, 1 },
    // 15: Chevrolet Corvette Z06
    { { DL, R2, DL, R2, L1, R1, L1, R1 }, T_CAR, 0, 0, 41100, 0, 1 },
    // 16: Chevrolet Corvette: NFS
    { { SQ, DR, DR, DR, R2, R1, R1, DR }, T_CAR, 1, 0, 41200, 0, 1 },
    // 17: Dodge Viper GTS: NFS
    { { L1, L2, L2, L2, DR, TR, TR, L2 }, T_CAR, 3, 0, 41201, 0, 1 },
    // 18: Ferrari F50
    { { L1, TR, L1, TR, DR, L2, DR, L2 }, T_CAR, 23, 0, 41113, 0, 1 },
    // 19: Ferrari F50: NFS
    { { TR, L1, L1, L1, DL, DR, DR, L1 }, T_CAR, 24, 0, 41212, 0, 1 },
    // 20: Lamborghini Diablo 6.0 VT
    { { DR, R2, DR, R2, R1, L1, R1, L1 }, T_CAR, 45, 0, 41125, 0, 1 },
    // 21: Lamborghini Diablo: NFS
    { { SQ, R2, R2, R2, TR, R1, R1, R2 }, T_CAR, 46, 0, 41220, 0, 1 },
    // 22: Lamborghini Murcielago
    { { R1, L2, R1, L2, L1, DR, L1, DR }, T_CAR, 47, 0, 41126, 0, 1 },
    // 23: Lamborghini Murcielago: NFS
    { { L1, R2, R2, R2, DL, SQ, SQ, R2 }, T_CAR, 48, 0, 41221, 0, 1 },
    // 24: Porsche 911 Turbo: NFS
    { { DR, DL, DL, DL, TR, R1, R1, DL }, T_CAR, 40, 0, 41217, 0, 1 },
    // 25: Porsche Carrera GT
    { { DL, DR, DL, DR, R1, R2, R1, R2 }, T_CAR, 17, 0, 41109, 0, 1 },
    // 26: Porsche Carrera GT: NFS
    { { R2, TR, TR, TR, R1, SQ, SQ, TR }, T_CAR, 18, 0, 41208, 0, 1 },
    // 27: Aston Martin V12 Vanquish
    { { R2, DR, R2, DR, TR, DL, TR, DL }, T_CAR, 29, 0, 41115, 0, 1 },
    // 28: V12 Vanquish: NFS
    { { SQ, DL, DL, DL, R1, R2, R2, DL }, T_CAR, 30, 0, 41214, 0, 1 },
    // 29: BMW Z8
    { { SQ, DR, SQ, DR, R2, TR, R2, TR }, T_CAR, 20, 0, 41111, 0, 1 },
    // 30: Ferrari 360 Challenge
    { { DL, SQ, SQ, SQ, R1, L2, L2, SQ }, T_CAR, 22, 0, 41211, 0, 1 },
    // 31: Ferrari 360 Spider
    { { R2, SQ, R2, SQ, TR, L2, TR, L2 }, T_CAR, 21, 0, 41112, 0, 1 },
    // 32: Ferrari 550 Barchetta
    { { L1, SQ, L1, SQ, DR, R1, DR, R1 }, T_CAR, 25, 0, 41127, 0, 1 },
    // 33: Ferrari 550 Barchetta: NFS
    { { SQ, R1, R1, R1, R2, DL, DL, R1 }, T_CAR, 26, 0, 41222, 0, 1 },
    // 34: Mustang Cobra R: NFS
    { { R1, DR, DR, DR, DL, R2, R2, DR }, T_CAR, 12, 0, 41205, 0, 1 },
    // 35: HSV Coupe GTS
    { { L1, L2, L1, L2, R1, TR, R1, TR }, T_CAR, 15, 0, 41108, 0, 1 },
    // 36: HSV Coupe GTS: NFS
    { { DR, L2, L2, L2, L1, DL, DL, L2 }, T_CAR, 16, 0, 41207, 0, 1 },
    // 37: Jaguar XKR: NFS
    { { L1, DR, DR, DR, L2, R1, R1, DR }, T_CAR, 28, 0, 41213, 0, 1 },
    // 38: Ford TS50
    { { DR, DL, DR, DL, R2, SQ, R2, SQ }, T_CAR, 13, 0, 41107, 0, 1 },
    // 39: Ford TS50: NFS
    { { DR, L1, L1, L1, R1, DL, DL, L1 }, T_CAR, 14, 0, 41206, 0, 1 },
    // 40: Lotus Elise
    { { TR, R2, TR, R2, DL, SQ, DL, SQ }, T_CAR, 41, 0, 41123, 0, 1 },
    // 41: Lotus Elise: NFS
    { { SQ, L1, L1, L1, R2, L2, L2, L1 }, T_CAR, 42, 0, 41218, 0, 1 },
    // 42: Mercedes CL55 AMG
    { { L1, DR, L1, DR, L2, SQ, L2, SQ }, T_CAR, 43, 0, 41124, 0, 1 },
    // 43: Mercedes CL55 AMG: NFS
    { { TR, R2, R2, R2, R1, L1, L1, R2 }, T_CAR, 44, 0, 41219, 0, 1 },
    // 44: Opel Speedster: NFS
    { { L2, R2, R2, R2, SQ, DL, DL, L2 }, T_CAR, 38, 0, 41216, 0, 1 },
    // 45: Vauxhall VX220: NFS
    { { L1, R1, R1, R1, DL, DR, DR, L1 }, T_CAR, 36, 0, 41215, 0, 1 },
    // 46: Pursuit Corvette Z06 in You're The Cop Mode
    { { R2, L1, L1, R2, R1, DR, DR, R1 }, T_COP_CAR, 33, 0, 990007, 0, 1 },
    // 47: Pursuit Corvette Z06 in all Challenge Modes
    { { L2, R2, R2, L2, TR, DR, TR, DR }, T_CAR, 33, 0, 990003, 0, 1 },
    // 48: Pursuit Murcielago in You're The Cop Mode
    { { DR, L2, L2, DR, SQ, DL, DL, SQ }, T_COP_CAR, 32, 0, 990006, 0, 1 },
    // 49: Pursuit Murcielago in all Challenge Modes
    { { R1, L1, L1, R1, DR, R2, DR, R2 }, T_CAR, 32, 0, 990002, 0, 1 },
    // 50: Pursuit Mustang Cobra R in You're The Cop Mode
    { { DL, TR, TR, DL, R1, R2, R2, R1 }, T_COP_CAR, 34, 0, 990008, 0, 1 },
    // 51: Pursuit Mustang Cobra R in all Challenge Modes
    { { DL, SQ, DL, SQ, R2, R1, R2, R1 }, T_CAR, 34, 0, 990004, 0, 1 },
    // 52: Pursuit M5 in You're The Cop Mode
    { { TR, SQ, SQ, TR, L1, R1, R1, L1 }, T_COP_CAR, 31, 0, 990005, 0, 1 },
    // 53: Pursuit M5 in all Challenge Modes
    { { SQ, TR, TR, SQ, DL, R1, DL, R1 }, T_CAR, 31, 0, 990001, 0, 1 },
    // 54: Pursuit Crown Victoria in all Challenge Modes
    { { DR, DL, DL, DR, SQ, TR, SQ, TR }, T_CAR, 4, 0, 990000, 0, 1 },
    // 55: Coastal Parklands II
    { { R2, R2, DL, DL, DL, R2, R1, L1 }, T_TRACK_BACK, 11, 0, 51009, 0, 1 },
    // 56: National Forest
    { { SQ, SQ, L2, L2, R1, R1, DL, DL }, T_TRACK, 12, 0, 50010, 0, 1 },
    // 57: National Forest II
    { { DL, DL, L1, L1, L1, DL, DR, SQ }, T_TRACK_BACK, 12, 0, 51010, 0, 1 },
    // 58: Scenic Drive II
    { { L2, L2, L1, L1, L1, L2, TR, SQ }, T_TRACK_BACK, 13, 0, 51011, 0, 1 },
    // 59: Desert Heat II
    { { R1, R1, R2, R2, R2, R1, L1, DL }, T_TRACK_BACK, 21, 0, 51013, 0, 1 },
    // 60: Outback
    { { TR, TR, DR, DR, L1, L1, R1, R1 }, T_TRACK, 22, 0, 50014, 0, 1 },
    // 61: Outback II
    { { L1, L1, TR, TR, TR, L1, SQ, DR }, T_TRACK_BACK, 22, 0, 51014, 0, 1 },
    // 62: Rocky Canyons
    { { R1, R1, DL, DL, SQ, SQ, DR, DR }, T_TRACK, 23, 0, 50025, 0, 1 },
    // 63: Rocky Canyons II
    { { SQ, SQ, TR, TR, TR, SQ, L1, DL }, T_TRACK_BACK, 23, 0, 51025, 0, 1 },
    // 64: Ancient Ruins II
    { { DR, DR, DL, DL, DL, DR, L1, SQ }, T_TRACK_BACK, 31, 0, 51015, 0, 1 },
    // 65: Calypso Coast
    { { R2, R2, R1, R1, L1, L1, TR, TR }, T_TRACK, 32, 0, 50016, 0, 1 },
    // 66: Calypso Coast II
    { { TR, TR, DR, DR, DR, TR, SQ, L1 }, T_TRACK_BACK, 32, 0, 51016, 0, 1 },
    // 67: Mediterranean Paradise II
    { { SQ, SQ, DR, DR, DR, SQ, DL, L2 }, T_TRACK_BACK, 33, 0, 51017, 0, 1 },
    // 68: Fall Winds II
    { { R2, R2, SQ, SQ, SQ, R2, DL, R1 }, T_TRACK_BACK, 41, 0, 51018, 0, 1 },
    // 69: Alpine Trail
    { { SQ, SQ, TR, TR, DL, DL, L2, L2 }, T_TRACK, 42, 0, 50019, 0, 1 },
    // 70: Alpine Trail II
    { { DL, DL, R2, R2, R2, DL, R1, SQ }, T_TRACK_BACK, 42, 0, 51019, 0, 1 },
    // 71: Autumn Crossing
    { { DR, DR, TR, TR, R1, R1, DL, DL }, T_TRACK, 43, 0, 50026, 0, 1 },
    // 72: Autumn Crossing II
    { { R1, R1, DR, DR, DR, R1, R2, TR }, T_TRACK_BACK, 43, 0, 51026, 0, 1 },
    // 73: Island Outskirts II
    { { L2, L2, R1, R1, R1, L2, DL, R2 }, T_TRACK_BACK, 61, 0, 51021, 0, 1 },
    // 74: Palm City Island
    { { DL, DL, R1, R1, DR, DR, SQ, SQ }, T_TRACK, 62, 0, 50022, 0, 1 },
    // 75: Palm City Island II
    { { DR, DR, R2, R2, R2, DR, R1, DL }, T_TRACK_BACK, 62, 0, 51022, 0, 1 },
    // 76: Tropical Circuit
    { { R2, R2, TR, TR, DR, DR, R1, R1 }, T_TRACK, 63, 0, 50023, 0, 1 },
    // 77: Tropical Circuit II
    { { L1, L1, DR, DR, DR, L1, SQ, R2 }, T_TRACK_BACK, 63, 0, 51023, 0, 1 },
};

#undef L1
#undef L2
#undef R1
#undef R2
#undef DL
#undef DR
#undef SQ
#undef TR
#undef NO
#undef T_EGG
#undef T_CAR
#undef T_COP_CAR
#undef T_TRACK
#undef T_TRACK_BACK

EasterEggs *eastereggs_construct(EasterEggs *e)
{
    e->vptr        = EASTEREGGS_VTABLE;
    e->Codes       = TheEasterEggCodes;
    e->NumCodes    = EASTEREGGS_NUM_CODES;
    e->Active      = 0;
    e->JustEntered = 0;
    e->LanguageID  = 0;
    e->Count       = 0;
    e->Head        = 0;
    return e;
}

void eastereggs_start(EasterEggs *e)
{
    JoyEvent ev;

    for (ev = JOY_EVENT_CHEAT_L1; ev <= JOY_EVENT_CHEAT_CIRCLE; ev++)
        AddJoyHandler(0, ev, eastereggs_joy_handler, e);
    e->JustEntered = 0;
    e->LanguageID  = 0;
    e->Active      = 1;
    eastereggs_reset(e);
}

void eastereggs_stop(EasterEggs *e)
{
    JoyEvent ev;

    for (ev = JOY_EVENT_CHEAT_L1; ev <= JOY_EVENT_CHEAT_CIRCLE; ev++)
        RemoveJoyHandler(0, ev);
    e->Active      = 0;
    e->JustEntered = 0;
    e->LanguageID  = 0;
    eastereggs_reset(e);
}

void eastereggs_reset(EasterEggs *e)
{
    e->Count = 0;
}

void eastereggs_on_button(EasterEggs *e, JoystickPort port, JoyEvent ev,
                          uint8_t value)
{
    uint32_t head, n, i, j;
    int32_t  matched;

    (void)port;
    (void)value;
    if (!e->Active)
        return;
    n = e->Count;
    if (n >= EASTEREGGS_CODE_LENGTH) {
        eastereggs_reset(e);
        return;
    }
    head     = e->Head;
    e->Count = n + 1;
    e->Ring[(head + n) & 7] = ev;
    if (n + 1 != EASTEREGGS_CODE_LENGTH)
        return;

    matched = 0;
    for (i = 0; i < e->NumCodes; i++) {
        EasterEggCode *c = &e->Codes[i];

        matched = 1;
        for (j = 0; j < EASTEREGGS_CODE_LENGTH; j++) {
            if (c->Buttons[j] != e->Ring[(head + j) & 7]) {
                matched = 0;
                break;
            }
        }
        if (matched) {
            eastereggs_clear_group(e, c->Group);
            c->On = 1;
            // A type-0 code's action, 0x0024fa48, is empty.
            e->JustEntered = 1;
            e->LanguageID  = c->LanguageID;
            eastereggs_reset(e);
            break;
        }
    }
    if (!matched) {
        e->Head  = (e->Head + 1) & 7;
        e->Count = e->Count - 1;
    }
}

void eastereggs_joy_handler(JoystickPort port, JoyEvent ev, uint8_t value,
                            void *obj)
{
    eastereggs_on_button((EasterEggs *)obj, port, ev, value);
}

void eastereggs_clear_temporary(EasterEggs *e)
{
    uint32_t i;

    for (i = 0; i < e->NumCodes; i++)
        if (e->Codes[i].Kept == 0)
            e->Codes[i].On = 0;
}

void eastereggs_clear_group(EasterEggs *e, int32_t group)
{
    uint32_t i;

    if (group == 0)
        return;
    for (i = 0; i < e->NumCodes; i++)
        if (e->Codes[i].Group == group)
            e->Codes[i].On = 0;
}

int32_t eastereggs_is_on(EasterEggs *e, int32_t type, int32_t param)
{
    uint32_t i;

    for (i = 0; i < e->NumCodes; i++) {
        const EasterEggCode *c = &e->Codes[i];

        if (c->Type == type && c->Param == param)
            return c->On;
    }
    return 0;
}

int32_t eastereggs_car_on(EasterEggs *e, int32_t car, int32_t cop)
{
    return eastereggs_is_on(e, cop ? EASTEREGG_TYPE_COP_CAR
                                   : EASTEREGG_TYPE_CAR, car);
}

int32_t eastereggs_track_on(EasterEggs *e, int32_t track, int32_t backward)
{
    return eastereggs_is_on(e, backward ? EASTEREGG_TYPE_TRACK_BACK
                                        : EASTEREGG_TYPE_TRACK, track);
}

int32_t eastereggs_egg_on(const EasterEggs *e, int32_t n)
{
    return e->Codes[n].On;
}

int32_t eastereggs_take_language_id(EasterEggs *e)
{
    e->JustEntered = 0;
    return e->LanguageID;
}

int32_t eastereggs_just_entered(const EasterEggs *e)
{
    return e->JustEntered;
}

int32_t eastereggs_is_active(const EasterEggs *e)
{
    return e->Active;
}

void eastereggs_enable(EasterEggs *e)
{
    e->Active = 1;
}

void eastereggs_disable(EasterEggs *e)
{
    e->Active = 0;
}
