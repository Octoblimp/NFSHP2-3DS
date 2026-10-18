// pausereplay -- HandlePauseMenuReplaySpecialEvents (0x001703e0), from
// retail. See pausereplay.h.

#include "pausereplay.h"

#include <stddef.h>

#include "aicarcontroller.h"
#include "car.h"
#include "cardamage.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "realdriver.h"
#include "world.h"

// PlayersByNumber[n] (gp-20936), which retail indexes with no test.
static struct Player *player_by_number(int32_t n)
{
    return n >= 0 && n < 2 ? PlayerPlayersByNumber[n] : NULL;
}

int32_t pause_menu_replay_special_event(const ReplaySpecialEventInfo *e)
{
    struct Player *p;
    int32_t i;

    switch (e->Type) {
    case PAUSE_EVENT_FORCE_FINISH:
        if (pCurrentRace != NULL) {
            pCurrentRace->ForceRaceFinishPlayerNum = e->B;
            pCurrentRace->ForceRaceFinishPosition = e->A;
        }
        return 1;
    case PAUSE_EVENT_HANDLING:
        p = player_by_number(e->A);
        if (p != NULL) {
            if (p->MyCar != NULL)
                p->MyCar->State.DriverMode = e->B;
            p->PlayerSettings.DrivingStyle = (int8_t)e->B;  // SetDrivingStyle
        }
        TheRaceParameters.NFSRaceMode = e->B;
        set_ai_driver_modes_from_players();
        return 1;
    case PAUSE_EVENT_DAMAGE:
        TheRaceParameters.DamageEnabled = e->A != 0;
        // The world and its count are read again after each car's.
        for (i = 0; pCurrentWorld != NULL && i < pCurrentWorld->TotalNumCars;
             i++) {
            struct Car *c = pCurrentWorld->CarTable[i];

            if (c != NULL && c->pCarDamage != NULL)
                cardamage_rethink_damage(c->pCarDamage);
        }
        return 1;
    case PAUSE_EVENT_TRANSMISSION:
        p = player_by_number(e->A);
        if (p == NULL)
            return 1;
        p->PlayerSettings.TransmissionType = (int8_t)e->B;
        if (p->MyCar != NULL && p->MyCar->pCarDriver != NULL)
            realdriver_set_manual_transmission(
                (RealDriver *)p->MyCar->pCarDriver, e->B);
        return 1;
    case PAUSE_EVENT_JUMP_CAMS:
        TheRaceParameters.GlobalDisplaySettings.JumpCams = (int8_t)e->A;
        return 1;
    case PAUSE_EVENT_ZONE_CAMS:
        TheRaceParameters.GlobalDisplaySettings.ZoneCams = (int8_t)e->A;
        return 1;
    case PAUSE_EVENT_SUPER_EASY_AI:
        SuperEasyAI = e->A;
        return 1;
    default:
        return 0;
    }
}
