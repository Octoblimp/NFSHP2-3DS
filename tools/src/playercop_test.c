// playercop_test -- tools/playercop_check.py's harness.
//
// Runs playercop.c over the checker's script. Everything it calls is a
// stub here that logs its arguments and answers from the script, as the
// model's stubs do. Pointers print as names: M the manager, A0.. cars,
// P0.. their players, C0.. cops, U0.. pursuits, H the helicopter and S the
// sample; anything else is "?".
//
//     playercop_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "car.h"
#include "chopper.h"
#include "cop.h"
#include "copmanager.h"
#include "playerhud.h"
#include "playerinit.h"
#include "playercop.h"
#include "pursuit.h"
#include "pursuitspeech.h"
#include "race.h"
#include "rcstates.h"
#include "realtime.h"
#include "world.h"

#define NCARS  8
#define NCOPS  3
#define NP     3

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
struct bSample *(*gGetInGameSampleFn)(const char *name);
void (*gSamplePlayFn)(struct bSample *s, float volume, float a, float b);

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
    for (i = 0; i < NCARS; i++) {
        if (p == &cars[i]) {
            snprintf(b, 16, "A%d", i);
            return b;
        }
        if (p == (const void *)players[i]) {
            snprintf(b, 16, "P%d", i);
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
            world.CarTable[i - 2] = &cars[ix(t[i])];
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
    for (k = 0; k < NCARS; k++)
        cars[k].pRacingCar = &rcs[k];
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
