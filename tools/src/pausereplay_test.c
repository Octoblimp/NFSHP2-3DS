// Drives pausereplay.c's HandlePauseMenuReplaySpecialEvents for
// tools/pausereplay_check.py (TASKS 72h-1). A script of ops, one per line,
// fields split on spaces; every number is decimal, taken mod 2^32:
//
//   state DMG MODE JUMP ZONE EASY FPOS FPNUM S0 T0 S1 T1 M0 M1
//         NCARS DMGMASK NULLMASK CAR0 CAR1 DRV0 DRV1 WORLD STUB
//         the whole state: TheRaceParameters' DamageEnabled, NFSRaceMode,
//         JumpCams and ZoneCams; SuperEasyAI; the Race's
//         ForceRaceFinishPosition and ForceRaceFinishPlayerNum; each
//         player's DrivingStyle and TransmissionType and its car's
//         DriverMode; the world's car count, which of its cars have a
//         CarDamage (DMGMASK) and which are NULL (NULLMASK); whether each
//         player has a car and each car a driver; whether pCurrentWorld is
//         set; and what the RethinkDamage stub does (0 nothing, 1 the
//         count down a car, 2 up a car to 8, 3 pCurrentWorld NULL)
//   ev TYPE A B the handler on that event
//
// Each event prints "ev T A B ret R", the stubs' calls, and the state.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "aicarcontroller.h"
#include "car.h"
#include "cardamage.h"
#include "pausereplay.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "realdriver.h"
#include "world.h"

#define CARS 8

struct Player *PlayerPlayersByNumber[2];
World *pCurrentWorld;
Race *pCurrentRace;
RaceParameters TheRaceParameters;
int32_t SuperEasyAI;

static struct Player players[2];
static struct Car cars[CARS];
static CarDamage damage[CARS];
static RealDriver drivers[2];
static World world;
static Race race;
static int stub;

void set_ai_driver_modes_from_players(void)
{
    printf("  ai modes\n");
}

void cardamage_rethink_damage(CarDamage *d)
{
    int k;

    for (k = 0; k < CARS && d != &damage[k]; k++)
        ;
    printf("  rethink D%d\n", k);
    if (stub == 1)
        world.TotalNumCars--;
    else if (stub == 2 && world.TotalNumCars < CARS)
        world.TotalNumCars++;
    else if (stub == 3)
        pCurrentWorld = NULL;
}

void realdriver_set_manual_transmission(RealDriver *d, int32_t m)
{
    printf("  manual R%d %d\n", d == &drivers[0] ? 0 : d == &drivers[1] ? 1 : 9,
           (int)m);
}

static void dump(void)
{
    int i;

    printf("  dmg %d mode %d jump %02x zone %02x easy %d force %d %d\n",
           (int)TheRaceParameters.DamageEnabled,
           (int)TheRaceParameters.NFSRaceMode,
           (unsigned)(uint8_t)TheRaceParameters.GlobalDisplaySettings.JumpCams,
           (unsigned)(uint8_t)TheRaceParameters.GlobalDisplaySettings.ZoneCams,
           (int)SuperEasyAI, (int)race.ForceRaceFinishPosition,
           (int)race.ForceRaceFinishPlayerNum);
    for (i = 0; i < 2; i++)
        printf("  p%d style %02x trans %02x car %d\n", i,
               (unsigned)(uint8_t)players[i].PlayerSettings.DrivingStyle,
               (unsigned)(uint8_t)players[i].PlayerSettings.TransmissionType,
               (int)cars[i].State.DriverMode);
    printf("  world %s cars %d\n", pCurrentWorld != NULL ? "W" : "NULL",
           (int)world.TotalNumCars);
}

int main(int argc, char **argv)
{
    char line[512];
    FILE *f;

    if (argc != 2 || (f = fopen(argv[1], "r")) == NULL) {
        printf("usage: pausereplay_test <script>\n");
        return 2;
    }
    PlayerPlayersByNumber[0] = &players[0];
    PlayerPlayersByNumber[1] = &players[1];
    pCurrentRace = &race;
    while (fgets(line, sizeof line, f) != NULL) {
        long v[22];
        int n, i, k;
        char *p = line;

        if (strncmp(line, "state ", 6) == 0) {
            p += 6;
            for (n = 0; n < 22; n++)
                v[n] = strtol(p, &p, 10);
            TheRaceParameters.DamageEnabled = (int32_t)v[0];
            TheRaceParameters.NFSRaceMode = (int32_t)v[1];
            TheRaceParameters.GlobalDisplaySettings.JumpCams = (int8_t)v[2];
            TheRaceParameters.GlobalDisplaySettings.ZoneCams = (int8_t)v[3];
            SuperEasyAI = (int32_t)v[4];
            race.ForceRaceFinishPosition = (int32_t)v[5];
            race.ForceRaceFinishPlayerNum = (int32_t)v[6];
            for (i = 0; i < 2; i++) {
                players[i].PlayerSettings.DrivingStyle = (int8_t)v[7 + 2 * i];
                players[i].PlayerSettings.TransmissionType =
                    (int8_t)v[8 + 2 * i];
                cars[i].State.DriverMode = (int32_t)v[11 + i];
                players[i].MyCar = v[16 + i] ? &cars[i] : NULL;
                cars[i].pCarDriver = v[18 + i] ? (CarDriver *)&drivers[i]
                                               : NULL;
            }
            world.TotalNumCars = (int32_t)v[13];
            for (k = 0; k < WORLD_MAX_CARS; k++) {
                world.CarTable[k] = k < CARS && !(v[15] >> k & 1) ? &cars[k]
                                                                 : NULL;
                if (k < CARS)
                    cars[k].pCarDamage = v[14] >> k & 1 ? &damage[k] : NULL;
            }
            pCurrentWorld = v[20] ? &world : NULL;
            stub = (int)v[21];
            printf("state\n");
            dump();
        } else if (strncmp(line, "ev ", 3) == 0) {
            ReplaySpecialEventInfo e;
            int32_t r;

            p += 3;
            e.Type = (int32_t)strtol(p, &p, 10);
            e.A = (int32_t)strtol(p, &p, 10);
            e.B = (int32_t)strtol(p, &p, 10);
            e.LoopCount = 0;
            printf("ev %d %d %d\n", (int)e.Type, (int)e.A, (int)e.B);
            r = pause_menu_replay_special_event(&e);
            printf("  ret %d\n", (int)r);
            dump();
        }
    }
    fclose(f);
    printf("faults 0\n");
    return 0;
}
