// playercop_test -- tools/playercop_check.py's harness.
//
// Runs playercop.c over the checker's script. Everything it calls is a
// stub here that logs its arguments and answers from the script, as the
// model's stubs do. Pointers print as names: M the manager, A0.. cars,
// P0.. their players, C0.. cops, U0.. pursuits, H the helicopter, S the
// sample, R the race, SM the speech manager, D0.. the cars' CarDamage and
// K0..+16 their controllers as ForceBoost gets them; anything else is "?".
//
//     playercop_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "car.h"
#include "carcontroller.h"
#include "chopper.h"
#include "cop.h"
#include "copmanager.h"
#include "copmgr.h"
#include "playerhud.h"
#include "playerinit.h"
#include "playercop.h"
#include "pursuit.h"
#include "pursuitspeech.h"
#include "race.h"
#include "racecore.h"
#include "racespeech.h"
#include "raceupdate.h"
#include "rcstates.h"
#include "realtime.h"
#include "speechmgr.h"
#include "vtable.h"
#include "world.h"

#define NCARS  8
#define NCOPS  3
#define NP     3

#define FAKE_VT     0x00500000u
#define BOOST_DELTA 16

static uint32_t fb(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float bf(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

// ---------------------------------------------------- what the port reads

tCopManager *pCopManager;
World       *pCurrentWorld;
Race        *pCurrentRace;
float        WorldTimeElapsed;
float        WorldTimeElapsedFrame;
RaceParameters TheRaceParameters;
struct bSample *(*gGetInGameSampleFn)(const char *name);
void (*gSamplePlayFn)(struct bSample *s, float volume, float a, float b);
void (*gCarDamageWreckFn)(void *damage);

static tCopManager    mgr;
static World          world;
static Race           race;
static Car            cars[NCARS];
static RacingCar      rcs[NCARS];
static char           players[NCARS][16];
static tPlayerCop     cops[NCOPS];
static tPursuit       ps[NP];
static struct Chopper chopper;
static char           sample[16];
static TimeAroundTrackTable tatt;
static Landmark       landmark;
static char           speechmgr[16];
static DriverInfo     drivers[NCARS];
static char           damages[NCARS][16];
static union {
    CarController c;
    uint8_t       b[64];
} ctls[NCARS];
static VtEntry boost_vt[VT_SLOT(CARCONTROLLER_VT_FORCE_BOOST) + 1];
static int     landmark_on;

static int     nis[NCARS], blink[NCARS], front[NCARS];
static int     sample_on = 1;
static int32_t request = 1;

static const char *sym(const void *p)
{
    static char buf[8][16];
    static int  k;
    char       *b = buf[k++ & 7];
    int         i;

    if (p == NULL)
        return "0";
    if (p == &mgr)
        return "M";
    if (p == &chopper)
        return "H";
    if (p == (const void *)sample)
        return "S";
    if (p == &race)
        return "R";
    if (p == (const void *)speechmgr)
        return "SM";
    for (i = 0; i < NCARS; i++) {
        if (p == &cars[i]) {
            snprintf(b, 16, "A%d", i);
            return b;
        }
        if (p == (const void *)players[i]) {
            snprintf(b, 16, "P%d", i);
            return b;
        }
        if (p == (const void *)damages[i]) {
            snprintf(b, 16, "D%d", i);
            return b;
        }
        if (p == (const void *)(ctls[i].b + BOOST_DELTA)) {
            snprintf(b, 16, "K%d+%d", i, BOOST_DELTA);
            return b;
        }
    }
    for (i = 0; i < NCOPS; i++)
        if (p == &cops[i] || p == &cops[i].Base) {
            snprintf(b, 16, "C%d", i);
            return b;
        }
    for (i = 0; i < NP; i++)
        if (p == &ps[i]) {
            snprintf(b, 16, "U%d", i);
            return b;
        }
    return "?";
}

static int car_index(const Car *c)
{
    int i;

    for (i = 0; i < NCARS; i++)
        if (c == &cars[i])
            return i;
    return -1;
}

// ---------------------------------------------------------------- stubs

int32_t player_is_nis_playing(const struct Player *p)
{
    int r = 0;
    int i;

    for (i = 0; i < NCARS; i++)
        if ((const void *)p == (const void *)players[i])
            r = nis[i];
    printf("  nis %s -> %d\n", sym(p), r);
    return r;
}

int32_t car_is_blinking(Car *c)
{
    int k = car_index(c);
    int r = k >= 0 ? blink[k] : 0;

    printf("  blink %s -> %d\n", sym(c), r);
    return r;
}

int32_t car_is_car_in_front(Car *c, Car *other, uint16_t angle)
{
    int k = car_index(other);
    int r = k >= 0 ? front[k] : 0;

    printf("  front %s %s %d -> %d\n", sym(c), sym(other), (int)angle, r);
    return r;
}

int32_t copmanager_request_pursuit(tCopManager *m, tCop *c, struct Car *car)
{
    printf("  request %s %s %s -> %d\n", sym(m), sym(c), sym(car),
           (int)request);
    return request;
}

void tpursuit_change_chase_target(tPursuit *p, struct Car *car)
{
    printf("  retarget %s %s\n", sym(p), sym(car));
}

void tpursuit_release_chopper(tPursuit *p)
{
    printf("  release %s\n", sym(p));
}

static struct bSample *get_sample(const char *name)
{
    struct bSample *r = sample_on ? (struct bSample *)(void *)sample : NULL;

    printf("  sample %s -> %s\n", name, sym(r));
    return r;
}

static void play(struct bSample *s, float volume, float a, float b)
{
    printf("  play %s %08x %08x %08x\n", sym(s), (unsigned)fb(volume),
           (unsigned)fb(a), (unsigned)fb(b));
}

void play_busted_speech(void)
{
    printf("  busted\n");
}

void be_a_cop_arrest_speech(int32_t players, int32_t missed, int32_t winner,
                            int32_t arrests)
{
    printf("  copspeech %d %d %d %d\n", (int)players, (int)missed,
           (int)winner, (int)arrests);
}

Landmark *copmgr_find_landmark(const bVector2 *pos)
{
    Landmark *r = landmark_on ? &landmark : NULL;

    printf("  landmark %08x %08x -> %s\n", (unsigned)fb(pos->x),
           (unsigned)fb(pos->y), r != NULL ? "L" : "0");
    return r;
}

SpeechMgr *speechmgr_get_instance(void)
{
    return (SpeechMgr *)(void *)speechmgr;
}

void speechmgr_raise_dispatch_be_on_lookout(SpeechMgr *m, int32_t location)
{
    printf("  lookout %s %d\n", sym(m), (int)location);
}

void race_finish_car_by_car(Race *r, struct Car *car, int32_t position,
                            int32_t blink, eRaceFinishReason reason)
{
    printf("  finish %s %s %d %d %d\n", sym(r), sym(car), (int)position,
           (int)blink, (int)reason);
}

void copmanager_delete_pursuit(tCopManager *m, tPursuit *p)
{
    printf("  delete %s %s\n", sym(m), sym(p));
}

// Retail's runs as it is, a store.
void tcop_set_pursuit(tCop *c, tPursuit *p)
{
    c->pMyPursuit = p;
}

static void wreck(void *damage)
{
    printf("  wreck %s\n", sym(damage));
}

static void boost(void *self, float f)
{
    printf("  boost %s %08x\n", sym(self), (unsigned)fb(f));
}

// ---------------------------------------------------------------- dumps

static uint32_t lights_word(const Car *c)
{
    uint32_t w;

    memcpy(&w, (const uint8_t *)c + offsetof(Car, CopLights), 4);
    return w;
}

static void cdump(int j)
{
    const tPlayerCop *c = &cops[j];
    const Car *car = c->Base.pMyCar;

    printf("C%d picks %d %d timers %08x %08x lights %08x siren %d\n", j,
           (int)c->nPrevSelection[0], (int)c->nPrevSelection[1],
           (unsigned)fb(c->fPrevSelectionTimer[0]),
           (unsigned)fb(c->fPrevSelectionTimer[1]),
           car != NULL ? (unsigned)lights_word(car) : 0u,
           car != NULL ? (int)car->TheSirenMode : 0);
}

static void bdump(void)
{
    int k;

    printf("beacop time %08x said %d busted %d pursuits %s %s %s\n",
           (unsigned)fb(mgr.fBeACopTime),
           (int)mgr.bBeACopAlreadySaidLookOutForSpeeders, (int)mgr.New10488,
           sym(cops[0].Base.pMyPursuit), sym(cops[1].Base.pMyPursuit),
           sym(cops[2].Base.pMyPursuit));
    for (k = 0; k < NCARS; k++)
        printf("A%d traction %08x damage %08x\n", k,
               (unsigned)fb(cars[k].fTractionBoostOverride),
               (unsigned)fb(cars[k].fDamageBoostOverride));
}

// ------------------------------------------------------------- the script

#define MAXT 24

static int split(char *line, char **t)
{
    int n = 0;
    char *s = line;

    for (;;) {
        char *bar = strchr(s, '|');

        if (n < MAXT)
            t[n++] = s;
        if (bar == NULL)
            break;
        *bar = 0;
        s = bar + 1;
    }
    return n;
}

static uint32_t hx(const char *s)
{
    return (uint32_t)strtoll(s, NULL, 0);
}

static int ix(const char *s)
{
    return (int)strtol(s, NULL, 0);
}

static void run(char **t, int n)
{
    const char *o = t[0];

    if (strcmp(o, "car") == 0) {
        int k = ix(t[1]);
        Car *c = &cars[k];
        uint32_t w = hx(t[10]);

        c->pPlayer = hx(t[2]) ? (Player *)(void *)players[k] : NULL;
        nis[k] = (int)hx(t[3]);
        c->State.Position.x = bf(hx(t[4]));
        c->State.Position.y = bf(hx(t[5]));
        c->State.Position.z = bf(hx(t[6]));
        rcs[k].FinishReason = (int16_t)hx(t[7]);
        blink[k] = (int)hx(t[8]);
        front[k] = (int)hx(t[9]);
        memcpy((uint8_t *)c + offsetof(Car, CopLights), &w, 4);
        c->TheSirenMode = (SirenMode)hx(t[11]);
    } else if (strcmp(o, "world") == 0) {
        int i;

        world.CopCarPos = ix(t[1]);
        for (i = 2; i < n; i++)
            world.CarTable[i - 2] = ix(t[i]) >= 0 ? &cars[ix(t[i])] : NULL;
    } else if (strcmp(o, "time") == 0) {
        WorldTimeElapsed = bf(hx(t[1]));
    } else if (strcmp(o, "pull") == 0) {
        mgr.CarPullovers[ix(t[1])].bActive = (int32_t)hx(t[2]);
    } else if (strcmp(o, "cop") == 0) {
        tPlayerCop *c = &cops[ix(t[1])];
        int u = ix(t[3]);

        c->Base.pMyCar = &cars[ix(t[2])];
        c->Base.pMyPursuit = u >= 0 ? &ps[u] : NULL;
        c->nPrevSelection[0] = (int32_t)hx(t[4]);
        c->nPrevSelection[1] = (int32_t)hx(t[5]);
        c->fPrevSelectionTimer[0] = bf(hx(t[6]));
        c->fPrevSelectionTimer[1] = bf(hx(t[7]));
    } else if (strcmp(o, "cpur") == 0) {
        int u = ix(t[2]);

        cops[ix(t[1])].Base.pMyPursuit = u >= 0 ? &ps[u] : NULL;
    } else if (strcmp(o, "pur") == 0) {
        tPursuit *p = &ps[ix(t[1])];
        int ch = ix(t[2]);

        p->pChasedCar = ch >= 0 ? &cars[ch] : NULL;
        p->pChopper = hx(t[3]) ? &chopper : NULL;
        chopper.TotalSalvos = (int32_t)hx(t[4]);
    } else if (strcmp(o, "mgr") == 0) {
        int j = ix(t[1]);

        mgr.nPlayerCopIndex = j < 0 ? -1 : 4;
        mgr.Cops[4] = j >= 0 ? &cops[j].Base : NULL;
    } else if (strcmp(o, "race") == 0) {
        race.RaceStage = (eRaceStage)hx(t[1]);
    } else if (strcmp(o, "cidx") == 0) {
        // cidx|k|index|drivertype|damage|racingcar
        int k = ix(t[1]);

        cars[k].CarIndex = (int16_t)ix(t[2]);
        drivers[k].TheDriverType = (DriverType)hx(t[3]);
        cars[k].pCarDamage = hx(t[4]) ? (CarDamage *)(void *)damages[k]
                                      : NULL;
        cars[k].pRacingCar = hx(t[5]) ? &rcs[k] : NULL;
    } else if (strcmp(o, "boosts") == 0) {
        int k = ix(t[1]);

        cars[k].fTractionBoostOverride = bf(hx(t[2]));
        cars[k].fDamageBoostOverride = bf(hx(t[3]));
    } else if (strcmp(o, "dmg") == 0) {
        mgr.fCarDamage[ix(t[1])] = bf(hx(t[2]));
    } else if (strcmp(o, "bac") == 0) {
        // bac|difficulty|time|said|busted|arrests
        mgr.nDifficultyLevel = (int32_t)hx(t[1]);
        mgr.fBeACopTime = bf(hx(t[2]));
        mgr.bBeACopAlreadySaidLookOutForSpeeders = (int32_t)hx(t[3]);
        mgr.New10488 = (int32_t)hx(t[4]);
        mgr.nBeACopNumArrestsMade = (int32_t)hx(t[5]);
    } else if (strcmp(o, "rp") == 0) {
        TheRaceParameters.NumPlayerCars = (int32_t)hx(t[1]);
        TheRaceParameters.Point2Point = (int32_t)hx(t[2]);
        TheRaceParameters.NumLapsInRace = (int32_t)hx(t[3]);
    } else if (strcmp(o, "rtime") == 0) {
        race.RaceTime.PackedTime = hx(t[1]);
        tatt.TotalTimeAroundTrack = bf(hx(t[2]));
    } else if (strcmp(o, "land") == 0) {
        landmark_on = (int)hx(t[1]);
        landmark.LandmarkType = (int32_t)hx(t[2]);
    } else if (strcmp(o, "beacop") == 0) {
        copmanager_be_a_cop_think(&mgr);
        bdump();
    } else if (strcmp(o, "sample") == 0) {
        sample_on = (int)hx(t[1]);
    } else if (strcmp(o, "request") == 0) {
        request = (int32_t)hx(t[1]);
    } else if (strcmp(o, "toggle") == 0) {
        int j;

        copmanager_be_a_cop_toggle_siren_and_lights(&mgr);
        printf("toggle\n");
        for (j = 0; j < NCOPS; j++)
            cdump(j);
    } else {
        int j = ix(t[1]);
        tPlayerCop *c = &cops[j];

        if (strcmp(o, "think") == 0)
            tplayercop_think(c);
        else if (strcmp(o, "change") == 0)
            tplayercop_change_chase_target(c);
        else if (strcmp(o, "select") == 0)
            printf("select C%d -> %s\n", j,
                   sym(tplayercop_select_car_to_chase(c)));
        else {
            fprintf(stderr, "unknown op %s\n", o);
            exit(2);
        }
        printf("%s C%d\n", o, j);
        cdump(j);
    }
}

int main(int argc, char **argv)
{
    static char line[4096];
    char *t[MAXT];
    FILE *f;
    int k;

    if (argc != 2) {
        fprintf(stderr, "usage: playercop_test script\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    pCopManager = &mgr;
    pCurrentWorld = &world;
    pCurrentRace = &race;
    mgr.nPlayerCopIndex = -1;
    gGetInGameSampleFn = get_sample;
    gSamplePlayFn = play;
    gCarDamageWreckFn = wreck;
    race.pTimeAroundTrackTable = &tatt;
    for (k = 0; k < NCARS; k++) {
        cars[k].pRacingCar = &rcs[k];
        cars[k].MyDriver = &drivers[k];
        cars[k].pCarController = &ctls[k].c;
        ctls[k].c._vtable = FAKE_VT;
    }
    boost_vt[VT_SLOT(CARCONTROLLER_VT_FORCE_BOOST)].delta = BOOST_DELTA;
    boost_vt[VT_SLOT(CARCONTROLLER_VT_FORCE_BOOST)].fn = (VtFn)boost;
    vt_install(FAKE_VT, boost_vt,
               (int)(sizeof boost_vt / sizeof boost_vt[0]));
    while (fgets(line, sizeof line, f) != NULL) {
        char *e = line + strlen(line);
        int n;

        while (e > line && (e[-1] == '\n' || e[-1] == '\r'))
            *--e = 0;
        if (line[0] == 0)
            continue;
        n = split(line, t);
        run(t, n);
    }
    fclose(f);
    return 0;
}
